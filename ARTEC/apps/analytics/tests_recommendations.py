import random
from datetime import date, timedelta

from django.test import TestCase
from django.urls import reverse

from apps.analytics import recommendations as reco
from apps.analytics.models import MLBatch, MLPrediction, ReviewStatus
from apps.common.testing import artec_user, make_submission, operator_user
from apps.feedback.models import Source

RND = random.Random(11)


def fill(code, lo, hi, n=30, **kw):
    return [make_submission(code, {"customer_service": RND.randint(lo, hi)}, collected_at=date.today() - timedelta(days=i % 10), **kw)
            for i in range(n)]


def verdicts(days=30):
    return {r["operator"].code: r for r in reco.compute_recommendations(window_days=days)["operators"]}


class RecommendationRulesTests(TestCase):
    def test_insufficient_sample_gives_no_recommendation(self):
        fill("orange", 8, 10, n=5)
        v = verdicts()["orange"]
        self.assertEqual(v["verdict"], reco.INSUFFICIENT)
        self.assertIsNone(v["rank"])

    def test_congratulate_warn_and_sanction_review(self):
        fill("orange", 8, 10)   # moyenne ~9
        fill("yas", 4, 6)       # moyenne ~5
        fill("airtel", 1, 3)    # moyenne ~2
        v = verdicts()
        self.assertEqual(v["orange"]["verdict"], reco.CONGRATULATE)
        self.assertEqual(v["orange"]["rank"], 1)
        self.assertEqual(v["yas"]["verdict"], reco.WARNING)
        self.assertEqual(v["airtel"]["verdict"], reco.SANCTION_REVIEW)
        self.assertEqual(v["airtel"]["rank"], 3)

    def test_good_but_not_distinct_is_only_compliant(self):
        fill("orange", 6, 8)
        fill("yas", 6, 8)
        v = verdicts()
        self.assertNotEqual(v["orange"]["verdict"], reco.SANCTION_REVIEW)
        self.assertNotIn(reco.CONGRATULATE, (v["orange"]["verdict"], v["yas"]["verdict"]))

    def test_old_data_outside_window_is_ignored(self):
        for _ in range(30):
            make_submission("orange", {"customer_service": 9}, collected_at=date.today() - timedelta(days=60))
        self.assertEqual(verdicts(30)["orange"]["verdict"], reco.INSUFFICIENT)  # « en temps réel » : fenêtre récente
        self.assertNotEqual(verdicts(90)["orange"]["verdict"], reco.INSUFFICIENT)

    def test_operator_imports_do_not_count_against_or_for_the_operator(self):
        fill("orange", 9, 10, source=Source.OPERATOR_IMPORT)
        self.assertEqual(verdicts()["orange"]["verdict"], reco.INSUFFICIENT)

    def test_confirmed_anomalies_are_excluded_and_unreviewed_flags_make_result_provisional(self):
        subs = fill("yas", 6, 8, n=40)
        batch = MLBatch.objects.create(period_start=date.today() - timedelta(days=30), period_end=date.today())
        for s in subs[:5]:   # 5 anomalies confirmées -> exclues
            MLPrediction.objects.create(batch=batch, submission=s, is_anomaly=True, review_status=ReviewStatus.CONFIRMED)
        for s in subs[5:12]:  # 7 alertes non examinées (>=10 % de 35) -> provisoire
            MLPrediction.objects.create(batch=batch, submission=s, is_anomaly=True)
        v = verdicts()["yas"]
        self.assertEqual(v["n_submissions"], 35)
        self.assertEqual(v["ml_flagged_unreviewed"], 7)
        self.assertTrue(v["provisional"])

    def test_unanalysed_window_is_flagged_provisional(self):
        fill("orange", 8, 10)
        self.assertTrue(verdicts()["orange"]["provisional"])


class RecommendationViewTests(TestCase):
    def test_artec_sees_page_and_invalid_window_falls_back(self):
        fill("orange", 8, 10)
        self.client.force_login(artec_user())
        r = self.client.get(reverse("artec:recommendations"), {"jours": 30})
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "aucune sanction automatique")
        self.assertEqual(self.client.get(reverse("artec:recommendations"), {"jours": "abc"}).status_code, 200)
        self.assertEqual(self.client.get(reverse("artec:recommendations"), {"jours": 9999}).context["reco"]["window_days"], 30)

    def test_operators_and_anonymous_cannot_access(self):
        self.assertEqual(self.client.get(reverse("artec:recommendations")).status_code, 302)
        self.client.force_login(operator_user("orange"))
        self.assertEqual(self.client.get(reverse("artec:recommendations")).status_code, 403)
