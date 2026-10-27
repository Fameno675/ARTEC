from django.db import transaction
from django.utils import timezone

from apps.audit.services import log
from apps.feedback.models import FeedbackSubmission, ValidationStatus

from .ml_client import MLUnavailable, get_ml_client
from .models import AnomalyReview, MLBatch, MLBatchStatus, MLPrediction, ReviewStatus

CONTRACT_VERSION = "1.0"
VALID_STATUS = {"succeeded", "partial", "failed"}


class BatchAlreadyProcessed(Exception):
    pass


def _observations_qs(batch):
    qs = FeedbackSubmission.objects.filter(
        validation_status=ValidationStatus.ACCEPTED, collected_at__gte=batch.period_start, collected_at__lte=batch.period_end
    ).select_related("operator").prefetch_related("ratings__criterion")
    if batch.operator_id:
        qs = qs.filter(operator=batch.operator)
    return qs.order_by("id")


def create_batch(*, requested_by, operator, start, end):
    batch = MLBatch.objects.create(requested_by=requested_by, operator=operator, period_start=start, period_end=end,
                                   contract_version=CONTRACT_VERSION)
    batch.n_observations = _observations_qs(batch).count()
    batch.save(update_fields=["n_observations"])
    log(requested_by, "ml.batch_created", batch, n=batch.n_observations)
    return batch


def build_request(batch):
    """Seules les observations ACCEPTÉES, sans client_hash, commentaire ni donnée personnelle."""
    obs = []
    for s in _observations_qs(batch):
        obs.append({"observation_id": str(s.id), "operator_code": s.operator.code, "collected_at": s.collected_at.isoformat(),
                    "source": s.source, "scores": {r.criterion.code: r.score for r in s.ratings.all()}})
    return {"batch_id": str(batch.id), "contract_version": batch.contract_version, "observations": obs}


def _finish(batch, status, code="", message=""):
    batch.status, batch.error_code, batch.error_message = status, code, message[:2000]
    batch.completed_at = timezone.now()
    batch.save()
    log(batch.requested_by, "ml.batch_finished", batch, status=status, error_code=code)
    return batch


def _validate_response(data, batch, sent_ids):
    if not isinstance(data, dict):
        raise ValueError("réponse non structurée")
    if data.get("batch_id") != str(batch.id):
        raise ValueError("batch_id différent")
    if str(data.get("contract_version", "")).split(".")[0] != CONTRACT_VERSION.split(".")[0]:
        raise ValueError("version de contrat incompatible")
    if data.get("status") not in VALID_STATUS:
        raise ValueError("statut invalide")
    seen = set()
    for r in data.get("results", []):
        oid = r.get("observation_id")
        if oid not in sent_ids or oid in seen:
            raise ValueError("observation inconnue ou dupliquée")
        seen.add(oid)
        for k in ("anomaly_score", "authenticity_probability"):
            v = r.get(k)
            if v is not None and not (isinstance(v, (int, float)) and 0 <= v <= 1):
                raise ValueError(f"{k} hors de [0, 1]")


def execute_batch(batch, client=None):
    """Exécute un lot ; ne lève jamais d'exception liée au moteur : le statut du lot porte l'échec."""
    with transaction.atomic():
        batch = MLBatch.objects.select_for_update().get(pk=batch.pk)
        if batch.status != MLBatchStatus.PENDING:
            raise BatchAlreadyProcessed(str(batch.id))  # idempotence : un batch_id n'est traité qu'une fois
        batch.status = MLBatchStatus.RUNNING
        batch.save(update_fields=["status"])
    payload = build_request(batch)
    sent_ids = {o["observation_id"] for o in payload["observations"]}
    batch.n_observations = len(sent_ids)
    if not sent_ids:
        return _finish(batch, MLBatchStatus.FAILED, "no_data", "Aucun avis accepté sur la période.")
    try:
        data = (client or get_ml_client()).analyze(payload)
    except MLUnavailable as exc:
        return _finish(batch, MLBatchStatus.UNAVAILABLE, "ml_unavailable", str(exc))
    except Exception as exc:
        return _finish(batch, MLBatchStatus.FAILED, "ml_exception", f"{type(exc).__name__}: {exc}")
    try:
        _validate_response(data, batch, sent_ids)
    except (ValueError, TypeError, AttributeError) as exc:
        return _finish(batch, MLBatchStatus.FAILED, "invalid_response", str(exc))

    errors = data.get("errors") or []
    if data["status"] == "failed":
        msg = "; ".join(f"{e.get('code')}: {e.get('message')}" for e in errors) or "Échec du moteur."
        return _finish(batch, MLBatchStatus.FAILED, (errors[0].get("code") if errors else "ml_failed"), msg)
    with transaction.atomic():  # résultats enregistrés en une seule transaction
        MLPrediction.objects.bulk_create([
            MLPrediction(batch=batch, submission_id=r["observation_id"], is_anomaly=r.get("is_anomaly"),
                         anomaly_score=r.get("anomaly_score"), authenticity_probability=r.get("authenticity_probability"),
                         reasons=r.get("reasons") or []) for r in data.get("results", [])
        ], batch_size=2000)
        batch.model_name, batch.model_version = data.get("model_name", ""), data.get("model_version", "")
        status = MLBatchStatus.PARTIAL if data["status"] == "partial" else MLBatchStatus.SUCCEEDED
        _finish(batch, status, errors[0].get("code", "") if errors else "",
                "; ".join(f"{e.get('code')}: {e.get('message')}" for e in errors))
    return batch


@transaction.atomic
def review_prediction(*, prediction, reviewer, outcome, notes=""):
    """Examen humain. N'a AUCUN effet sur les réclamations ni sur les décisions réglementaires."""
    if outcome not in ReviewStatus.values or outcome == ReviewStatus.UNREVIEWED:
        raise ValueError("Résultat d'examen invalide.")
    rev = AnomalyReview.objects.create(prediction=prediction, reviewer=reviewer, outcome=outcome, notes=notes)
    prediction.review_status = outcome
    prediction.save(update_fields=["review_status"])
    log(reviewer, "ml.prediction_reviewed", prediction, outcome=outcome)
    return rev
