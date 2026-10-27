import uuid

from django.conf import settings
from django.db import models

from apps.common.storage import get_private_storage


class DataSourceType(models.TextChoices):
    PUBLIC_FORM = "public_form", "Formulaire public"
    OPERATOR_FILE = "operator_file", "Fichier opérateur"
    ARTEC_FILE = "artec_file", "Fichier ARTEC"
    SURVEY_EXPORT = "survey_export", "Export de sondage"
    SOCIAL_EXPORT = "social_export", "Export de données sociales"
    OFFICIAL_API = "official_api", "API officielle / accès autorisé"


class DataSource(models.Model):
    """Provenance d'un jeu de données (traçabilité et limites d'usage)."""

    name = models.CharField("nom", max_length=200, unique=True)
    source_type = models.CharField(max_length=20, choices=DataSourceType.choices)
    provenance = models.TextField("provenance", blank=True)
    collected_from = models.DateField("collecte du", null=True, blank=True)
    collected_to = models.DateField("collecte au", null=True, blank=True)
    usage_limits = models.TextField("limites d'utilisation", blank=True)
    legal_basis = models.TextField("base légale / autorisation", blank=True)
    is_active = models.BooleanField(default=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]
        verbose_name = "source de données"

    def __str__(self):
        return self.name


class ImportStatus(models.TextChoices):
    UPLOADED = "uploaded", "Téléversé"
    VALIDATED = "validated", "Validé"
    COMMITTED = "committed", "Enregistré"
    FAILED = "failed", "Échec"
    CANCELLED = "cancelled", "Annulé"


class ImportBatch(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    data_source = models.ForeignKey(DataSource, on_delete=models.PROTECT, related_name="batches")
    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    operator = models.ForeignKey("operators.Operator", null=True, blank=True, on_delete=models.PROTECT, related_name="import_batches")
    original_filename = models.CharField(max_length=255)
    stored_file = models.FileField(upload_to="imports/", storage=get_private_storage, blank=True)
    file_sha256 = models.CharField(max_length=64, blank=True)
    file_size = models.BigIntegerField(default=0)
    file_format = models.CharField(max_length=10, blank=True)
    schema_version = models.CharField(max_length=30, default="feedback_import_v1")
    status = models.CharField(max_length=12, choices=ImportStatus.choices, default=ImportStatus.UPLOADED, db_index=True)
    total_rows = models.PositiveIntegerField(default=0)
    accepted_rows = models.PositiveIntegerField(default=0)
    rejected_rows = models.PositiveIntegerField(default=0)
    review_rows = models.PositiveIntegerField(default=0)
    duplicate_rows = models.PositiveIntegerField(default=0)
    error_summary = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "import"

    @property
    def rejection_rate(self):
        return (self.rejected_rows / self.total_rows) if self.total_rows else 0.0


class RowStatus(models.TextChoices):
    ACCEPTED = "accepted", "Accepté"
    REJECTED = "rejected", "Rejeté"
    TO_REVIEW = "to_review", "À examiner"


class ImportRowResult(models.Model):
    batch = models.ForeignKey(ImportBatch, on_delete=models.CASCADE, related_name="rows")
    row_number = models.PositiveIntegerField()
    status = models.CharField(max_length=10, choices=RowStatus.choices, db_index=True)
    error_codes = models.JSONField(default=list, blank=True)
    raw_data = models.JSONField(default=dict, blank=True)
    submission = models.ForeignKey("feedback.FeedbackSubmission", null=True, blank=True, on_delete=models.SET_NULL, related_name="import_rows")

    class Meta:
        ordering = ["row_number"]
        indexes = [models.Index(fields=["batch", "status"])]
