import uuid

from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils import timezone


class CriterionCategory(models.TextChoices):
    MOBILE_DATA = "mobile_data", "Internet mobile"
    CALLS = "calls", "Appels"
    SMS = "sms", "SMS"
    PRICING = "pricing", "Tarification"
    CREDIT_PLANS = "credit_plans", "Crédit et forfaits"
    MOBILE_MONEY = "mobile_money", "Mobile money"
    CUSTOMER_SERVICE = "customer_service", "Service client"


class Criterion(models.Model):
    code = models.SlugField(max_length=60, unique=True)
    category = models.CharField(max_length=30, choices=CriterionCategory.choices)
    label = models.CharField("libellé", max_length=150)
    description = models.CharField(max_length=300, blank=True)
    is_active = models.BooleanField("actif", default=True)
    position = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["position", "id"]
        verbose_name = "critère"

    def __str__(self):
        return self.label


class SurveyForm(models.Model):
    slug = models.SlugField(max_length=80, unique=True)
    title = models.CharField("titre", max_length=200)
    description = models.TextField(blank=True)
    starts_at = models.DateTimeField("début", null=True, blank=True)
    ends_at = models.DateTimeField("fin", null=True, blank=True)
    is_active = models.BooleanField("actif", default=True)
    # Échelle verrouillée en v1 (contrainte DB ci-dessous).
    scale_min = models.PositiveSmallIntegerField(default=0, editable=False)
    scale_max = models.PositiveSmallIntegerField(default=10, editable=False)
    criteria = models.ManyToManyField(Criterion, through="SurveyFormCriterion", related_name="surveys")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "formulaire de sondage"
        constraints = [
            models.CheckConstraint(name="survey_scale_locked_0_10", condition=Q(scale_min=0, scale_max=10)),
        ]

    def __str__(self):
        return self.title

    def is_open(self, now=None):
        now = now or timezone.now()
        if not self.is_active:
            return False
        if self.starts_at and now < self.starts_at:
            return False
        if self.ends_at and now > self.ends_at:
            return False
        return True


class SurveyFormCriterion(models.Model):
    survey_form = models.ForeignKey(SurveyForm, on_delete=models.CASCADE, related_name="survey_criteria")
    criterion = models.ForeignKey(Criterion, on_delete=models.PROTECT, related_name="+")
    position = models.PositiveSmallIntegerField(default=0)
    is_required = models.BooleanField(default=False)

    class Meta:
        ordering = ["position", "id"]
        constraints = [
            models.UniqueConstraint(fields=["survey_form", "criterion"], name="uniq_survey_criterion"),
        ]


class Source(models.TextChoices):
    PUBLIC_FORM = "public_form", "Formulaire public"
    OPERATOR_IMPORT = "operator_import", "Import opérateur"
    ARTEC_IMPORT = "artec_import", "Import ARTEC"
    EXTERNAL_IMPORT = "external_import", "Source externe"


class ValidationStatus(models.TextChoices):
    PENDING = "pending", "En attente"
    ACCEPTED = "accepted", "Accepté"
    TO_REVIEW = "to_review", "À examiner"
    REJECTED = "rejected", "Rejeté"


class FeedbackSubmission(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    survey_form = models.ForeignKey(SurveyForm, null=True, blank=True, on_delete=models.SET_NULL, related_name="submissions")
    operator = models.ForeignKey("operators.Operator", on_delete=models.PROTECT, related_name="submissions")
    collected_at = models.DateField("date de collecte", db_index=True)
    submitted_at = models.DateTimeField(default=timezone.now)
    source = models.CharField(max_length=20, choices=Source.choices, db_index=True)
    data_source = models.ForeignKey("datasets.DataSource", null=True, blank=True, on_delete=models.PROTECT, related_name="submissions")
    import_batch = models.ForeignKey("datasets.ImportBatch", null=True, blank=True, on_delete=models.SET_NULL, related_name="submissions")
    external_id = models.CharField(max_length=100, blank=True)
    dedup_hash = models.CharField(max_length=64, blank=True, db_index=True)
    content_hash = models.CharField(max_length=64, blank=True)
    validation_status = models.CharField(max_length=10, choices=ValidationStatus.choices, default=ValidationStatus.PENDING, db_index=True)
    validation_reasons = models.JSONField(default=list, blank=True)
    # Pseudonymes techniques (HMAC), jamais envoyés au ML, purgés après 30 jours.
    client_hash = models.CharField(max_length=64, blank=True, db_index=True)
    device_hash = models.CharField(max_length=64, blank=True, db_index=True)
    comment = models.CharField(max_length=500, blank=True)

    class Meta:
        ordering = ["-submitted_at"]
        verbose_name = "avis"
        indexes = [models.Index(fields=["operator", "collected_at", "validation_status"])]

    def __str__(self):
        return f"Avis {self.id} ({self.operator_id})"


class FeedbackRating(models.Model):
    submission = models.ForeignKey(FeedbackSubmission, on_delete=models.CASCADE, related_name="ratings")
    criterion = models.ForeignKey(Criterion, on_delete=models.PROTECT, related_name="ratings")
    score = models.SmallIntegerField()

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["submission", "criterion"], name="uniq_rating_per_criterion"),
            models.CheckConstraint(name="rating_score_0_10", condition=Q(score__gte=0, score__lte=10)),
        ]
