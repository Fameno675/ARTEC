"""Adaptateur : contrat backend v1.0 (apps.analytics) <-> moteur ML complet (`analyze_batch`).

Le backend continue de parler le contrat 1.0 (observation_id, operator_code, scores par code de critère
Django...) ; ce module traduit vers les colonnes du moteur, appelle `analyze_batch`, puis retraduit la
réponse. Il n'ajoute aucune donnée personnelle : le moteur ne reçoit ni empreinte d'appareil ni commentaire.
"""
from __future__ import annotations

from datetime import datetime, timezone

from .contract import CONTRACT_VERSION, AnalysisError, AnalysisRequest, AnalysisResponse, ObservationResult, Reason
from .prediction import analyze_batch
from .schemas import ENGINE_VERSION, EngineConfig

MODEL_NAME = "artec_ml_engine"

# code de critère Django (apps.feedback.constants) -> colonne du moteur
CRITERION_MAP = {
    "mobile_data_speed": "internet_vitesse",
    "mobile_data_stability": "internet_stabilite",
    "mobile_data_availability": "internet_disponibilite",
    "call_audio_quality": "appels_qualite_sonore",
    "call_success_stability": "appels_reussite",
    "sms_reliability": "sms_fiabilite",
    "pricing_value": "tarification",
    "credit_purchase_ease": "credit_forfaits",
    "mobile_money_reliability": "mobile_money",
    "customer_service": "service_client",
}
# source Django -> source du moteur
SOURCE_MAP = {
    "public_form": "public_review",
    "operator_import": "operator_file",
    "artec_import": "survey",
    "external_import": "external",
}
# Statut d'authenticité du moteur -> is_anomaly du contrat (jamais « authentique » : voir README du moteur)
ANOMALY_BY_STATUS = {"needs_review": True, "no_anomaly_detected": False}


def build_config(salt: str, **overrides) -> EngineConfig:
    cfg = EngineConfig(
        visitor_salt=salt,
        # Les avis du backend ne portent qu'une DATE de collecte (pas d'heure) : la détection de pics horaires
        # n'aurait aucun sens, on la neutralise plutôt que de fabriquer des heures.
        burst_min_count=10**9,
        include_review_in_scores=False,
    )
    for k, v in overrides.items():
        setattr(cfg, k, v)
    return cfg


def _to_rows(observations) -> list[dict]:
    rows = []
    for o in observations:
        row = {
            "obs_id": o.observation_id,
            "operator": o.operator_code,
            "source": SOURCE_MAP.get(o.source, "unspecified"),
            # date seule -> midi heure de Madagascar (UTC+3), sans pretendre à une heure réelle
            "submitted_at": f"{str(o.collected_at)[:10]}T12:00:00+03:00",
            # Pas d'identifiant d'appareil (vie privée) : un jeton unique par avis évite de déclarer « doublon exact »
            # deux visiteurs différents qui auraient donné les mêmes notes le même jour.
            "visitor_id": o.observation_id,
        }
        for code, value in (o.scores or {}).items():
            key = CRITERION_MAP.get(code)
            if key is not None and value is not None:
                row[key] = value
        rows.append(row)
    return rows


def _clamp01(v):
    if v is None:
        return None
    try:
        return min(1.0, max(0.0, float(v)))
    except (TypeError, ValueError):
        return None


class ArtecMLEngine:
    """Implémente le protocole `AnomalyEngine` du contrat 1.0."""

    def __init__(self, config: EngineConfig | None = None, salt: str = "CHANGE-ME-IN-PRODUCTION"):
        self.config = config or build_config(salt)

    def analyze(self, request: AnalysisRequest) -> AnalysisResponse:
        now = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
        if request.contract_version.split(".")[0] != CONTRACT_VERSION.split(".")[0]:
            return AnalysisResponse(request.batch_id, CONTRACT_VERSION, MODEL_NAME, ENGINE_VERSION, "failed", [],
                                    [AnalysisError("unsupported_contract_version", request.contract_version)], now)
        raw = analyze_batch(_to_rows(request.observations), metadata={"batch_id": request.batch_id}, config=self.config)

        results, sent = [], {o.observation_id for o in request.observations}
        for r in raw.get("observation_results", []):
            oid = str(r.get("obs_id"))
            if oid not in sent:
                continue
            results.append(ObservationResult(
                observation_id=oid,
                is_anomaly=ANOMALY_BY_STATUS.get(r.get("authenticity_status")),  # None = non évalué / structure invalide
                anomaly_score=_clamp01(r.get("anomaly_score")),
                authenticity_probability=_clamp01(r.get("authenticity_probability")),  # None sans modèle supervisé qualifié
                reasons=[Reason(x.get("code", ""), x.get("message", ""), x.get("feature")) for x in r.get("reasons", [])],
            ))
        errors = [AnalysisError(e.get("code", "error"), e.get("message", "")) for e in raw.get("errors", [])]
        status = {"failed": "failed", "partial": "partial"}.get(raw.get("status"), "succeeded")
        version = raw.get("model_version") or ENGINE_VERSION
        return AnalysisResponse(request.batch_id, CONTRACT_VERSION, MODEL_NAME, str(version), status, results, errors, now)
