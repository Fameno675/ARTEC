import time
from unittest import mock

from django.test import TestCase, override_settings
from django.urls import reverse

from apps.common.testing import artec_user, operator_user
from apps.feedback import antispam
from apps.feedback.models import FeedbackRating, FeedbackSubmission, SurveyForm, ValidationStatus

SLUG = "satisfaction-generale"


class PublicFormBase(TestCase):
    def setUp(self):
        self.url = reverse("public:survey_detail", args=[SLUG])
        # temps de remplissage neutralisé sauf dans les tests dédiés
        self.patch = mock.patch("apps.feedback.antispam.time.time", side_effect=self._clock)
        self._now = 1_000_000.0
        self.token = antispam.make_form_token()  # émis à _now
        self.patch.start()
        self.addCleanup(self.patch.stop)

    def _clock(self):
        return self._now

    def fresh_token(self, wait=10):
        self._now = 1_000_000.0
        tok = antispam.make_form_token()
        self._now += wait
        return tok

    def post(self, data=None, client=None, wait=10, **extra):
        payload = {"operator": "orange", "score_mobile_data_speed": "7", "comment": "", "website": ""}
        payload.update(data or {})
        payload["form_ts"] = payload.get("form_ts", self.fresh_token(wait))
        return (client or self.client).post(self.url, payload, **extra)


class PublicFeedbackTests(PublicFormBase):
    def test_get_form_no_account_needed(self):
        r = self.client.get(self.url)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(r.context["criteria_fields"]), 10)
        self.assertEqual(r.context["scale"], {"min": 0, "max": 10})

    def test_valid_submission_saved(self):
        r = self.post({"score_mobile_data_speed": "8", "score_customer_service": "3"})
        self.assertRedirects(r, reverse("public:survey_thanks", args=[SLUG]), fetch_redirect_response=False)
        sub = FeedbackSubmission.objects.get()
        self.assertEqual(sub.validation_status, ValidationStatus.ACCEPTED)
        self.assertEqual(sub.source, "public_form")
        self.assertEqual(sub.operator.code, "orange")
        self.assertEqual(dict(sub.ratings.values_list("criterion__code", "score")), {"mobile_data_speed": 8, "customer_service": 3})

    def test_score_bounds_enforced(self):
        for bad in ("11", "-1", "7.5", "abc", "100"):
            r = self.post({"score_mobile_data_speed": bad})
            self.assertEqual(r.status_code, 200, bad)
            self.assertTrue(r.context["form"].errors, bad)
        self.assertEqual(FeedbackSubmission.objects.count(), 0)

    def test_boundaries_0_and_10_accepted(self):
        self.post({"score_mobile_data_speed": "0", "score_customer_service": "10"})
        self.assertEqual(sorted(FeedbackRating.objects.values_list("score", flat=True)), [0, 10])

    def test_at_least_one_score_required(self):
        r = self.post({"score_mobile_data_speed": ""})
        self.assertEqual(FeedbackSubmission.objects.count(), 0)
        self.assertContains(r, "au moins un critère")

    def test_unknown_or_inactive_operator_rejected(self):
        r = self.post({"operator": "inconnu"})
        self.assertEqual(FeedbackSubmission.objects.count(), 0)
        self.assertTrue(r.context["form"].errors["operator"])

    def test_db_constraint_rejects_out_of_range_even_bypassing_form(self):
        from django.db import IntegrityError, transaction
        sub = FeedbackSubmission.objects.create(operator_id=1, collected_at="2026-01-01", source="public_form")
        from apps.feedback.models import Criterion
        with self.assertRaises(IntegrityError), transaction.atomic():
            FeedbackRating.objects.create(submission=sub, criterion=Criterion.objects.first(), score=11)

    def test_honeypot_silently_ignored(self):
        r = self.post({"website": "http://spam"})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(FeedbackSubmission.objects.count(), 0)

    def test_too_fast_submission_refused(self):
        r = self.post(wait=1)
        self.assertEqual(FeedbackSubmission.objects.count(), 0)
        self.assertContains(r, "trop vite")

    def test_missing_token_refused(self):
        r = self.post({"form_ts": ""})
        self.assertEqual(FeedbackSubmission.objects.count(), 0)

    def test_same_device_limited_per_operator_24h_but_other_operator_allowed(self):
        self.post()
        self.assertEqual(FeedbackSubmission.objects.count(), 1)
        r = self.post()  # même appareil (cookie conservé), même opérateur
        self.assertEqual(FeedbackSubmission.objects.count(), 1)
        self.assertContains(r, "déjà évalué")
        self.post({"operator": "yas"})  # un visiteur peut évaluer plusieurs opérateurs
        self.assertEqual(FeedbackSubmission.objects.count(), 2)

    def test_visitor_not_tied_to_single_operator(self):
        self.post({"operator": "orange"})
        self.post({"operator": "airtel"})
        self.assertEqual(set(FeedbackSubmission.objects.values_list("operator__code", flat=True)), {"orange", "airtel"})

    def test_shared_connection_not_blocked(self):
        """Plusieurs appareils derrière la même IP : tous acceptés sous le seuil."""
        from django.test import Client
        for _ in range(5):
            self.post(client=Client(), REMOTE_ADDR="10.0.0.1", HTTP_USER_AGENT="same")
        self.assertEqual(FeedbackSubmission.objects.filter(validation_status="accepted").count(), 5)

    @override_settings(FEEDBACK_NETWORK_REVIEW_PER_HOUR=3, FEEDBACK_NETWORK_BLOCK_PER_HOUR=100)
    def test_network_burst_goes_to_review_not_blocked(self):
        from django.test import Client
        for _ in range(5):
            r = self.post(client=Client(), REMOTE_ADDR="10.0.0.2", HTTP_USER_AGENT="ua")
            self.assertEqual(r.status_code, 302)
        statuses = list(FeedbackSubmission.objects.order_by("submitted_at").values_list("validation_status", flat=True))
        self.assertEqual(statuses, ["accepted"] * 3 + ["to_review"] * 2)

    @override_settings(FEEDBACK_NETWORK_REVIEW_PER_HOUR=2, FEEDBACK_NETWORK_BLOCK_PER_HOUR=4)
    def test_network_flood_gets_429(self):
        from django.test import Client
        codes = [self.post(client=Client(), REMOTE_ADDR="10.0.0.3", HTTP_USER_AGENT="ua").status_code for _ in range(6)]
        self.assertEqual(codes[:4], [302] * 4)
        self.assertEqual(codes[4:], [429, 429])

    def test_no_raw_personal_data_stored(self):
        self.post(REMOTE_ADDR="203.0.113.7", HTTP_USER_AGENT="Mozilla/5.0 Secret")
        sub = FeedbackSubmission.objects.get()
        blob = " ".join(str(getattr(sub, f.name)) for f in sub._meta.fields)
        self.assertNotIn("203.0.113.7", blob)
        self.assertNotIn("Secret", blob)
        self.assertEqual(len(sub.client_hash), 64)

    def test_purge_client_hashes(self):
        from datetime import timedelta
        from django.utils import timezone
        from apps.feedback.services import purge_client_hashes
        self.post()
        FeedbackSubmission.objects.update(submitted_at=timezone.now() - timedelta(days=31))
        self.assertEqual(purge_client_hashes(), 1)
        self.assertEqual(FeedbackSubmission.objects.get().client_hash, "")

    def test_comment_with_url_goes_to_review(self):
        self.post({"comment": "voir http://spam.example"})
        self.assertEqual(FeedbackSubmission.objects.get().validation_status, "to_review")

    def test_comment_length_limited(self):
        r = self.post({"comment": "x" * 501})
        self.assertEqual(FeedbackSubmission.objects.count(), 0)

    def test_closed_survey_is_404(self):
        SurveyForm.objects.update(is_active=False)
        self.assertEqual(self.client.get(self.url).status_code, 404)

    def test_survey_outside_period_is_404(self):
        from datetime import timedelta
        from django.utils import timezone
        SurveyForm.objects.update(ends_at=timezone.now() - timedelta(days=1))
        self.assertEqual(self.client.get(self.url).status_code, 404)

    def test_form_never_collects_name_or_phone(self):
        r = self.client.get(self.url)
        self.assertEqual(set(r.context["form"].fields) - {f"score_{c.code}" for c in r.context["form"].criteria},
                         {"operator", "comment", "form_ts", "website"})


class ArtecSurveyAdminTests(TestCase):
    def test_create_survey_with_criteria_and_locked_scale(self):
        from apps.feedback.models import Criterion
        self.client.force_login(artec_user())
        ids = list(Criterion.objects.values_list("pk", flat=True)[:3])
        r = self.client.post(reverse("artec:survey_create"), {
            "title": "Sondage T4", "slug": "t4", "description": "d", "is_active": "on", "criteria_selection": ids})
        self.assertEqual(r.status_code, 302)
        s = SurveyForm.objects.get(slug="t4")
        self.assertEqual((s.scale_min, s.scale_max), (0, 10))
        self.assertEqual(s.criteria.count(), 3)

    def test_end_before_start_rejected(self):
        from apps.feedback.models import Criterion
        self.client.force_login(artec_user())
        r = self.client.post(reverse("artec:survey_create"), {
            "title": "X", "slug": "x", "starts_at": "2026-05-01T10:00", "ends_at": "2026-04-01T10:00",
            "criteria_selection": [Criterion.objects.first().pk]})
        self.assertEqual(r.status_code, 200)
        self.assertFalse(SurveyForm.objects.filter(slug="x").exists())

    def test_operator_cannot_manage_surveys(self):
        self.client.force_login(operator_user())
        self.assertEqual(self.client.get(reverse("artec:survey_create")).status_code, 403)

    def test_review_flow_accept_reject(self):
        from apps.common.testing import make_submission
        s = make_submission("orange", {"mobile_data_speed": 5}, status="to_review")
        self.client.force_login(artec_user())
        self.client.post(reverse("artec:feedback_validate", args=[s.pk]), {"decision": "accept"})
        s.refresh_from_db()
        self.assertEqual(s.validation_status, "accepted")
        self.assertEqual(self.client.post(reverse("artec:feedback_validate", args=[s.pk]), {"decision": "reject"}).status_code, 400)
