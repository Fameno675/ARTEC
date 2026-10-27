import uuid

from django.conf import settings
from django.db import models
from django.db.models import Q


class MLBatchStatus(models.TextChoices):
    PENDING = "pending", "En attente"
    RUNNING = "running", "En cours"
    SUCCEEDED = "succeeded", "Réussie"
    PARTIAL = "partial", "Partielle"
    FAILED = "failed", "Échec"
    UNAVAILABLE = "unavailable", "Moteur indisponible"


class MLBatch(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)  # = batch_id du contrat
    requested_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    operator = models.ForeignKey("operators.Operator", null=True, blank=True, on_delete=models.PROTECT, related_name="ml_batches")
    period_start = models.DateField()
    period_end = models.DateField()
    contract_version = models.CharField(max_length=10, default="1.0")
    model_name = models.CharField(max_length=80, blank=True)
    model_version = models.CharField(max_length=40, blank=True)
    status = models.CharField(max_length=12, choices=MLBatchStatus.choices, default=MLBatchStatus.PENDING, db_index=True)
    n_observations = models.PositiveIntegerField(default=0)
    error_code = models.CharField(max_length=60, blank=True)
    error_message = models.TextField(blank=True)
    submitted_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-submitted_at"]
        verbose_name = "lot d'analyse ML"

    @property
    def awaiting_or_failed(self):
        return self.status in (MLBatchStatus.PENDING, MLBatchStatus.RUNNING, MLBatchStatus.FAILED, MLBatchStatus.UNAVAILABLE)


class ReviewStatus(models.TextChoices):
    UNREVIEWED = "unreviewed", "Non examinée"
    CONFIRMED = "confirmed", "Anomalie confirmée par un humain"
    DISMISSED = "dismissed", "Écartée après examen"
    NEEDS_INFO = "needs_info", "Informations requises"


class MLPrediction(models.Model):
    batch = models.ForeignKey(MLBatch, on_delete=models.CASCADE, related_name="predictions")
    submission = models.ForeignKey("feedback.FeedbackSubmission", on_delete=models.CASCADE, related_name="predictions")
    is_anomaly = models.BooleanField(null=True)
    anomaly_score = models.FloatField(null=True, blank=True)  # 0-1, PAS une probabilité
    authenticity_probability = models.FloatField(null=True, blank=True)
    reasons = models.JSONField(default=list, blank=True)
    review_status = models.CharField(max_length=12, choices=ReviewStatus.choices, default=ReviewStatus.UNREVIEWED, db_index=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["batch", "submission"], name="uniq_prediction_per_batch"),
            models.CheckConstraint(name="anomaly_score_0_1", condition=Q(anomaly_score__isnull=True) | Q(anomaly_score__gte=0, anomaly_score__lte=1)),
            models.CheckConstraint(name="authenticity_0_1", condition=Q(authenticity_probability__isnull=True) | Q(authenticity_probability__gte=0, authenticity_probability__lte=1)),
        ]


class AnomalyReview(models.Model):
    prediction = models.ForeignKey(MLPrediction, on_delete=models.CASCADE, related_name="reviews")
    reviewer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    outcome = models.CharField(max_length=12, choices=ReviewStatus.choices)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
