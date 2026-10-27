"""Clients du moteur ML. Interface unique : analyze(dict) -> dict (JSON-compatible).

LocalMLClient : appel Python à ml_engine ; UnavailableMLClient : moteur désactivé.
Un futur client HTTP pourra remplacer le client local sans changer le contrat.
"""
from dataclasses import asdict

from django.conf import settings


class MLUnavailable(Exception):
    pass


class UnavailableMLClient:
    def analyze(self, request: dict) -> dict:
        raise MLUnavailable("Moteur ML désactivé (ML_ENGINE_BACKEND=unavailable).")


class LocalMLClient:
    """Moteur complet (ml_engine.adapter) ; ML_ENGINE_BACKEND=local_basic pour l'ancien moteur v0.1 (repli)."""

    def __init__(self, basic: bool = False):
        self.basic = basic

    def analyze(self, request: dict) -> dict:
        try:
            from ml_engine.contract import AnalysisRequest, Observation
            if self.basic:
                from ml_engine.engine import IsolationForestEngine
                engine = IsolationForestEngine(min_observations_for_model=settings.ML_MIN_OBSERVATIONS_FOR_MODEL)
            else:
                from ml_engine.adapter import ArtecMLEngine
                engine = ArtecMLEngine(salt=settings.ML_VISITOR_SALT)
        except ImportError as exc:  # scikit-learn / pandas absents
            raise MLUnavailable(f"Moteur ML non installé : {exc}")
        req = AnalysisRequest(
            batch_id=request["batch_id"], contract_version=request["contract_version"],
            observations=[Observation(**o) for o in request["observations"]],
        )
        return asdict(engine.analyze(req))


def get_ml_client():
    backend = settings.ML_ENGINE_BACKEND
    if backend == "local":
        return LocalMLClient()
    if backend == "local_basic":
        return LocalMLClient(basic=True)
    return UnavailableMLClient()
