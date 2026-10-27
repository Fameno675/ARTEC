import random
from datetime import date, timedelta
from unittest import mock

from django.test import TestCase, override_settings
from django.urls import reverse

from apps.analytics import indicators as ind
from apps.analytics import services
from apps.analytics.ml_client import MLUnavailable, UnavailableMLClient
from apps.analytics.models import AnomalyReview, MLBatch, MLPrediction
from apps.common.testing import artec_user, make_submission, op, operator_user
from apps.complaints.models import ArtecDecision, Complaint
from apps.feedback.models import FeedbackSubmission

TODAY = date.today()


class IndicatorTests(TestCase):
    def test_mean_distribution_and_sentiment_rule(self):
        # notes : 0, 4 (négatif) ; 5, 6 (neutre) ; 7, 10 (positif)
        for v in (0, 4, 5, 6, 7, 10):
            make_submission("orange", {"mobile_data_speed": v})
        c = ind.compute_indicators(operator=op("orange"))["criteria"][0]
        self.assertEqual(c["code"], "mobile_data_speed")
        self.assertEqual(c["n_ratings"], 6)
        self.assertEqual(c["mean"], 5.33)
        self.assertEqual((c["negative_rate"], c["neutral_rate"], c["positive_rate"]), (0.3333, 0.3333, 0.3333))
        self.assertEqual(c["distribution"]["0"], 1)
        self.assertEqual(c["distribution"]["10"], 1)
        self.assertEqual(sum(c["distribution"].values()), 6)
        self.assertEqual(len(c["distribution"]), 11)
        self.assertEqual(len(c["ci95"]), 2)

    def test_small_sample_flagged_and_large_not(self):
        for _ in range(5):
            make_submission("orange", {"customer_service": 5})
        r = ind.compute_indicators(operator=op("orange"))
        self.assertFalse(r["sample_sufficient"])
        self.assertTrue(any("insuffisant" in l for l in r["limitations"]))
        self.assertFalse(r["criteria"][0]["sample_sufficient"])
        for _ in range(30):
            make_submission("yas", {"customer_service": 5})
        r = ind.compute_indicators(operator=op("yas"))
        self.assertTrue(r["sample_sufficient"])
        self.assertFalse(any("insuffisant" in l for l in r["limitations"]))

    def test_only_accepted_counted(self):
        make_submission("orange", {"customer_service": 9})
        make_submission("orange", {"customer_service": 1}, status="to_review")
        make_submission("orange", {"customer_service": 1}, status="rejected")
        r = ind.compute_indicators(operator=op("orange"))
        self.assertEqual((r["n_submissions"], r["criteria"][0]["mean"]), (1, 9.0))

    def test_period_filter(self):
        make_submission("orange", {"customer_service": 9}, collected_at=TODAY - timedelta(days=100))
        make_submission("orange", {"customer_service": 3}, collected_at=TODAY - timedelta(days=5))
        r = ind.compute_indicators(operator=op("orange"), start=TODAY - timedelta(days=30), end=TODAY)
        self.assertEqual((r["n_submissions"], r["criteria"][0]["mean"]), (1, 3.0))
        self.assertEqual(r["period"]["start"], (TODAY - timedelta(days=30)).isoformat())

    def test_operator_imports_excluded_from_comparisons_by_default(self):
        make_submission("orange", {"customer_service": 9}, source="public_form")
        make_submission("orange", {"customer_service": 1}, source="operator_import")
        self.assertEqual(ind.compute_indicators(operator=op("orange"))["n_submissions"], 1)
        self.assertEqual(ind.compute_indicators(operator=op("orange"), include_operator_imports=True)["n_submissions"], 2)

    def test_count_by_operator_and_period_and_time_series(self):
        make_submission("orange", {"customer_service": 4}, collected_at=date(2026, 1, 10))
        make_submission("orange", {"customer_service": 8}, collected_at=date(2026, 1, 20))
        make_submission("orange", {"customer_service": 6}, collected_at=date(2026, 2, 3))
        make_submission("yas", {"customer_service": 6}, collected_at=date(2026, 2, 3))
        rows = ind.submissions_by_operator_and_period(granularity="month")
        self.assertIn({"operator": "orange", "period": "2026-01-01", "n": 2}, rows)
        self.assertIn({"operator": "yas", "period": "2026-02-01", "n": 1}, rows)
        ts = ind.time_series(operator=op("orange"), granularity="month")
        self.assertEqual([(t["period"], t["n_submissions"], t["quality_score"]) for t in ts], [("2026-01-01", 2, 6.0), ("2026-02-01", 1, 6.0)])

    def test_complaints_by_status_and_import_stats(self):
        from apps.common.testing import csv_upload, recent_date
        from apps.datasets.importer import process_import
        from apps.datasets.models import DataSource
        u = operator_user("orange")
        Complaint.objects.create(reference="R1", complainant_operator=op("orange"), target_operator=op("yas"), subject="s", description="d")
        Complaint.objects.create(reference="R2", complainant_operator=op("orange"), target_operator=op("yas"), subject="s", description="d", status="closed")
        c = ind.complaints_by_status()
        self.assertEqual((c["received"], c["closed"], c["rejected"]), (1, 1, 0))
        d = recent_date()
        body = "collected_at,score_customer_service\n" + "".join(f"{d},{i}\n" for i in range(9)) + f"{d},99\n"
        process_import(uploaded_file=csv_upload(body), user=u, data_source=DataSource.objects.create(name="s", source_type="operator_file"), operator_scope=u.operator)
        s = ind.import_stats()
        self.assertEqual((s["total_rows"], s["rejected_rows"], s["rejection_rate"]), (10, 1, 0.1))

    def test_empty_data_does_not_crash(self):
        r = ind.compute_indicators(operator=op("airtel"))
        self.assertEqual((r["n_submissions"], r["criteria"], r["quality_score"]), (0, [], None))

    def test_bad_filter_params_fall_back_safely(self):
        f = ind.parse_filters({"start": "nope", "granularity": "decade"})
        self.assertEqual((f["start"], f["granularity"]), (None, "month"))


def fill(n, operator="orange", straight=0):
    rnd = random.Random(1)
    codes = ["mobile_data_speed", "mobile_data_stability", "call_audio_quality", "customer_service", "pricing_value"]
    for _ in range(n):
        make_submission(operator, {c: rnd.randint(3, 8) for c in codes})
    for _ in range(straight):
        make_submission(operator, {c: 10 for c in codes})


class MLIntegrationTests(TestCase):
    def new_batch(self, operator=None):
        return services.create_batch(requested_by=artec_user(), operator=operator, start=TODAY - timedelta(days=30), end=TODAY)

    def test_unavailable_engine_keeps_backend_working_and_data_intact(self):
        fill(10)
        before = FeedbackSubmission.objects.count()
        with override_settings(ML_ENGINE_BACKEND="unavailable"):
            b = services.execute_batch(self.new_batch())
        self.assertEqual((b.status, b.error_code), ("unavailable", "ml_unavailable"))
        self.assertEqual(MLPrediction.objects.count(), 0)
        self.assertEqual(FeedbackSubmission.objects.count(), before)
        self.assertTrue(b.awaiting_or_failed)
        self.client.force_login(artec_user())
        self.assertContains(self.client.get(reverse("artec:dashboard")), "en attente ou en échec")
        self.assertContains(self.client.get(reverse("artec:mlbatch_detail", args=[b.pk])), "en attente ou en échec")

    def test_engine_exception_marks_failed_without_crashing(self):
        fill(5)
        client = mock.Mock()
        client.analyze.side_effect = RuntimeError("segfault simulé")
        b = services.execute_batch(self.new_batch(), client=client)
        self.assertEqual((b.status, b.error_code), ("failed", "ml_exception"))
        self.assertIn("segfault", b.error_message)
        self.assertEqual(MLPrediction.objects.count(), 0)

    def test_missing_ml_dependency_is_reported_unavailable(self):
        fill(5)
        with mock.patch.dict("sys.modules", {"ml_engine.adapter": None, "ml_engine.engine": None}):
            b = services.execute_batch(self.new_batch())
        self.assertEqual(b.status, "unavailable")

    def test_malformed_or_hostile_responses_rejected_atomically(self):
        fill(5)
        sid = str(FeedbackSubmission.objects.first().id)
        for i, bad in enumerate([
            "pas un dict",
            {"batch_id": "autre", "contract_version": "1.0", "status": "succeeded", "results": []},
            {"batch_id": None, "contract_version": "2.0", "status": "succeeded", "results": []},
            {"batch_id": None, "contract_version": "1.0", "status": "weird", "results": []},
            {"batch_id": None, "contract_version": "1.0", "status": "succeeded", "results": [{"observation_id": "inconnue"}]},
            {"batch_id": None, "contract_version": "1.0", "status": "succeeded", "results": [{"observation_id": sid, "anomaly_score": 1.7}]},
            {"batch_id": None, "contract_version": "1.0", "status": "succeeded", "results": [{"observation_id": sid, "authenticity_probability": -0.1}]},
        ]):
            batch = self.new_batch()
            if isinstance(bad, dict) and bad.get("batch_id") is None:
                bad = {**bad, "batch_id": str(batch.id)}
            client = mock.Mock()
            client.analyze.return_value = bad
            b = services.execute_batch(batch, client=client)
            self.assertEqual((b.status, b.error_code), ("failed", "invalid_response"), i)
        self.assertEqual(MLPrediction.objects.count(), 0)

    def test_engine_reports_failed_status(self):
        fill(5)
        batch = self.new_batch()
        client = mock.Mock()
        client.analyze.return_value = {"batch_id": str(batch.id), "contract_version": "1.0", "status": "failed", "results": [],
                                       "errors": [{"code": "model_not_loaded", "message": "x"}]}
        self.assertEqual(services.execute_batch(batch, client=client).error_code, "model_not_loaded")

    def test_no_data_batch_fails_cleanly(self):
        b = services.execute_batch(self.new_batch())
        self.assertEqual((b.status, b.error_code), ("failed", "no_data"))

    def test_batch_is_idempotent(self):
        fill(5)
        batch = self.new_batch()
        services.execute_batch(batch)
        with self.assertRaises(services.BatchAlreadyProcessed):
            services.execute_batch(batch)

    def test_payload_contains_only_accepted_and_no_personal_data(self):
        fill(3)
        s = make_submission("orange", {"customer_service": 5}, status="to_review")
        FeedbackSubmission.objects.update(client_hash="SECRETHASH", device_hash="SECRETDEV", comment="mon numero 034 00 000 00")
        payload = services.build_request(self.new_batch())
        self.assertEqual(len(payload["observations"]), 3)
        self.assertNotIn(str(s.id), str(payload))
        blob = str(payload)
        for forbidden in ("SECRETHASH", "SECRETDEV", "034 00", "comment", "client_hash"):
            self.assertNotIn(forbidden, blob)
        self.assertEqual(set(payload["observations"][0]), {"observation_id", "operator_code", "collected_at", "source", "scores"})

    def test_real_local_engine_end_to_end_flags_straight_lining(self):
        fill(120, straight=4)
        # Moteur de repli v0.1 (ML_ENGINE_BACKEND=local_basic) ; le moteur complet est testé dans tests_engine.py
        with override_settings(ML_ENGINE_BACKEND="local_basic", ML_MIN_OBSERVATIONS_FOR_MODEL=50):
            b = services.execute_batch(self.new_batch())
        self.assertEqual(b.status, "succeeded", b.error_message)
        self.assertEqual((b.model_name, b.model_version), ("rules_isolation_forest", "0.1.0"))
        self.assertEqual(MLPrediction.objects.count(), 124)
        straight = [p for p in MLPrediction.objects.all() if any(r["code"] == "straight_lining" for r in p.reasons)]
        self.assertEqual(len(straight), 4)
        self.assertTrue(all(p.is_anomaly for p in straight))
        scores = [p.anomaly_score for p in MLPrediction.objects.all()]
        self.assertTrue(all(s is not None and 0 <= s <= 1 for s in scores))
        self.assertTrue(all(p.authenticity_probability is None for p in MLPrediction.objects.all()))  # jamais inventée
        self.assertTrue(all("message" in r for p in straight for r in p.reasons))

    @override_settings(ML_ENGINE_BACKEND="local_basic")
    def test_small_batch_uses_rules_only_with_null_score(self):
        fill(5, straight=1)
        b = services.execute_batch(self.new_batch())
        self.assertEqual(b.status, "succeeded")
        self.assertTrue(all(p.anomaly_score is None for p in MLPrediction.objects.all()))
        self.assertEqual(MLPrediction.objects.filter(is_anomaly=True).count(), 1)

    @override_settings(ML_ENGINE_BACKEND="local_basic")
    def test_partial_status_when_model_part_fails(self):
        fill(60)
        with mock.patch("sklearn.ensemble.IsolationForest.fit", side_effect=ValueError("boom")):
            b = services.execute_batch(self.new_batch())
        self.assertEqual((b.status, b.error_code), ("partial", "model_error"))
        self.assertEqual(MLPrediction.objects.count(), 60)  # règles conservées

    def test_prediction_never_creates_decision_or_changes_complaint(self):
        fill(60, straight=3)
        c = Complaint.objects.create(reference="R1", complainant_operator=op("orange"), target_operator=op("yas"), subject="s", description="d")
        b = services.execute_batch(self.new_batch())
        self.assertEqual(b.status, "succeeded")
        c.refresh_from_db()
        self.assertEqual(c.status, "received")
        self.assertEqual(ArtecDecision.objects.count(), 0)
        self.assertFalse(FeedbackSubmission.objects.exclude(validation_status="accepted").exists())  # aucun avis modifié

    def test_human_review_recorded_without_side_effects(self):
        fill(5, straight=1)
        b = services.execute_batch(self.new_batch())
        pred = MLPrediction.objects.get(is_anomaly=True)
        a = artec_user()
        services.review_prediction(prediction=pred, reviewer=a, outcome="confirmed", notes="Vérifié manuellement.")
        pred.refresh_from_db()
        self.assertEqual(pred.review_status, "confirmed")
        self.assertEqual(AnomalyReview.objects.count(), 1)
        self.assertEqual(ArtecDecision.objects.count(), 0)
        with self.assertRaises(ValueError):
            services.review_prediction(prediction=pred, reviewer=a, outcome="unreviewed")

    def test_db_constraints_on_scores(self):
        from django.db import IntegrityError, transaction
        fill(2)
        b = services.execute_batch(self.new_batch(), client=mock.Mock(analyze=mock.Mock(return_value={"x": 1})))
        sub = FeedbackSubmission.objects.first()
        with self.assertRaises(IntegrityError), transaction.atomic():
            MLPrediction.objects.create(batch=b, submission=sub, anomaly_score=1.5)

    def test_operator_scoped_batch_only_sends_that_operator(self):
        fill(4, "orange")
        fill(6, "yas")
        p = services.build_request(self.new_batch(op("yas")))
        self.assertEqual({o["operator_code"] for o in p["observations"]}, {"yas"})
        self.assertEqual(len(p["observations"]), 6)


class MLViewTests(TestCase):
    def test_views_and_permissions(self):
        fill(5, straight=1)
        self.client.force_login(operator_user())
        self.assertEqual(self.client.get(reverse("artec:mlbatch_list")).status_code, 403)
        self.assertEqual(self.client.post(reverse("artec:mlbatch_list"), {"start": "2026-01-01", "end": "2026-12-31"}).status_code, 403)
        self.client.force_login(artec_user())
        r = self.client.post(reverse("artec:mlbatch_list"), {"start": (TODAY - timedelta(days=10)).isoformat(), "end": TODAY.isoformat()})
        b = MLBatch.objects.get()
        self.assertRedirects(r, reverse("artec:mlbatch_detail", args=[b.pk]), fetch_redirect_response=False)
        r = self.client.get(reverse("artec:mlbatch_detail", args=[b.pk]) + "?anomalies=1")
        self.assertContains(r, "n’est pas une probabilité")
        pred = MLPrediction.objects.get(is_anomaly=True)
        self.client.post(reverse("artec:prediction_review", args=[pred.pk]), {"outcome": "dismissed", "notes": "RAS"})
        pred.refresh_from_db()
        self.assertEqual(pred.review_status, "dismissed")

    def test_management_command(self):
        from django.core.management import call_command
        from io import StringIO
        fill(5)
        out = StringIO()
        call_command("run_ml_analysis", start=(TODAY - timedelta(days=10)).isoformat(), end=TODAY.isoformat(), stdout=out)
        self.assertIn("succeeded", out.getvalue())
