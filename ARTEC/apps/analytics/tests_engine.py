"""Intégration du moteur ML complet (ml_engine.adapter) au contrat backend v1.0."""
import random
from datetime import date, timedelta

from unittest import mock

from django.test import SimpleTestCase, TestCase, override_settings

from apps.analytics import services
from apps.analytics.ml_client import LocalMLClient
from apps.analytics.models import MLBatch, MLBatchStatus
from apps.common.testing import artec_user, make_submission, op
from ml_engine.adapter import CRITERION_MAP, ArtecMLEngine
from ml_engine.contract import AnalysisRequest, Observation

CODES = list(CRITERION_MAP)


def _normal_obs(n, seed=7):
    rnd = random.Random(seed)
    out = []
    for i in range(n):
        base = rnd.gauss(6, 1.3)
        scores = {c: max(0, min(10, round(base + rnd.gauss(0, 1.2)))) for c in CODES if rnd.random() < 0.85} or {CODES[0]: 5}
        out.append(Observation(f"n{i}", rnd.choice(["orange", "yas", "airtel"]),
                               (date.today() - timedelta(days=i % 20)).isoformat(), "public_form", scores))
    return out


class AdapterContractTests(SimpleTestCase):
    def setUp(self):
        self.engine = ArtecMLEngine(salt="test-salt")

    def test_response_respects_contract(self):
        obs = _normal_obs(60)
        r = self.engine.analyze(AnalysisRequest("b-1", "1.0", obs))
        self.assertEqual(r.status, "succeeded")
        self.assertEqual(r.batch_id, "b-1")
        ids = {o.observation_id for o in obs}
        self.assertTrue({x.observation_id for x in r.results} <= ids)
        for x in r.results:
            self.assertIsNone(x.authenticity_probability)  # pas de modèle supervisé : jamais de fausse probabilité
            if x.anomaly_score is not None:
                self.assertTrue(0 <= x.anomaly_score <= 1)

    def test_incompatible_contract_version_fails_cleanly(self):
        r = self.engine.analyze(AnalysisRequest("b", "2.0", _normal_obs(5)))
        self.assertEqual(r.status, "failed")
        self.assertEqual(r.errors[0].code, "unsupported_contract_version")

    def test_extreme_patterns_are_flagged_with_explicit_reasons(self):
        obs = _normal_obs(80)
        obs.append(Observation("all0", "yas", date.today().isoformat(), "public_form", {c: 0 for c in CODES}))
        obs.append(Observation("alt", "airtel", date.today().isoformat(), "public_form",
                               {c: (0 if k % 2 else 10) for k, c in enumerate(CODES)}))
        res = {x.observation_id: x for x in self.engine.analyze(AnalysisRequest("b", "1.0", obs)).results}
        self.assertTrue(res["all0"].is_anomaly)
        self.assertIn("uniform_extreme_ratings", [r.code for r in res["all0"].reasons])
        self.assertTrue(res["alt"].is_anomaly)
        self.assertIn("extreme_only_ratings", [r.code for r in res["alt"].reasons])
        normal_flagged = sum(1 for k, x in res.items() if k.startswith("n") and x.is_anomaly)
        self.assertLessEqual(normal_flagged, 2)

    def test_identical_scores_from_different_visitors_are_not_duplicates(self):
        same = {"mobile_data_speed": 7, "customer_service": 7, "call_audio_quality": 7}
        obs = [Observation(f"s{i}", "orange", date.today().isoformat(), "public_form", dict(same)) for i in range(5)]
        res = self.engine.analyze(AnalysisRequest("b", "1.0", obs)).results
        self.assertEqual(len(res), 5)  # aucun n'est écarté comme « doublon exact »
        self.assertTrue(all(x.is_anomaly is not True for x in res))

    def test_unknown_criterion_and_missing_values_are_ignored(self):
        obs = [Observation("a", "orange", date.today().isoformat(), "public_form",
                           {"mobile_data_speed": 8, "inconnu": 3, "customer_service": None})]
        r = self.engine.analyze(AnalysisRequest("b", "1.0", obs))
        self.assertIn(r.status, ("succeeded", "partial"))


class EndToEndBatchTests(TestCase):
    def test_real_engine_through_execute_batch(self):
        rnd = random.Random(3)
        for _ in range(40):
            make_submission("orange", {c: rnd.randint(4, 9) for c in CODES}, collected_at=date.today() - timedelta(days=rnd.randint(0, 10)))
        make_submission("yas", {c: 0 for c in CODES})
        batch = services.create_batch(requested_by=artec_user(), operator=None,
                                      start=date.today() - timedelta(days=30), end=date.today())
        batch = services.execute_batch(batch, client=LocalMLClient())
        batch.refresh_from_db()
        self.assertIn(batch.status, (MLBatchStatus.SUCCEEDED, MLBatchStatus.PARTIAL))
        self.assertEqual(batch.model_name, "artec_ml_engine")
        self.assertEqual(batch.predictions.count(), 41)
        flagged = batch.predictions.filter(is_anomaly=True)
        self.assertEqual(flagged.count(), 1)
        self.assertEqual(flagged.first().submission.operator, op("yas"))


class FullEngineBatchBehaviourTests(TestCase):
    """Équivalents, pour le moteur complet, des garanties vérifiées sur le moteur de repli."""

    def _batch(self):
        return services.create_batch(requested_by=artec_user(), operator=None,
                                     start=date.today() - timedelta(days=30), end=date.today())

    def test_small_batch_rules_only_flags_extreme_uniform_profile(self):
        rnd = random.Random(1)
        codes = ["mobile_data_speed", "mobile_data_stability", "call_audio_quality", "customer_service", "pricing_value"]
        for _ in range(5):
            make_submission("orange", {c: rnd.randint(3, 8) for c in codes})
        make_submission("orange", {c: 10 for c in codes})
        b = services.execute_batch(self._batch())
        self.assertEqual(b.status, MLBatchStatus.SUCCEEDED, b.error_message)
        self.assertEqual(b.predictions.filter(is_anomaly=True).count(), 1)

    def test_model_failure_keeps_rule_results_and_marks_batch_partial(self):
        rnd = random.Random(2)
        for _ in range(210):   # >= 200 : le moteur tente l'Isolation Forest
            make_submission("orange", {c: rnd.randint(3, 8) for c in CODES})
        with mock.patch("sklearn.ensemble.IsolationForest.fit", side_effect=ValueError("boom")):
            b = services.execute_batch(self._batch())
        self.assertEqual(b.status, MLBatchStatus.PARTIAL, b.error_message)
        self.assertEqual(b.predictions.count(), 210)  # la validation et les règles sont conservées

    @override_settings(ML_ENGINE_BACKEND="local_basic")
    def test_legacy_engine_remains_selectable(self):
        for i in range(5):
            make_submission("orange", {"customer_service": 5 + i % 3})
        b = services.execute_batch(self._batch())
        self.assertEqual(b.model_name, "rules_isolation_forest")
