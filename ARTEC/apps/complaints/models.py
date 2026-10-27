import uuid

from django.conf import settings
from django.db import models
from django.db.models import F, Q

from apps.common.storage import get_private_storage


class ComplaintStatus(models.TextChoices):
    RECEIVED = "received", "Reçue"
    UNDER_REVIEW = "under_review", "En cours d'examen"
    INFO_REQUESTED = "info_requested", "Informations complémentaires demandées"
    CLOSED = "closed", "Clôturée"
    REJECTED = "rejected", "Rejetée"


# Transitions autorisées (clôturée / rejetée sont finales).
ALLOWED_TRANSITIONS = {
    ComplaintStatus.RECEIVED: {ComplaintStatus.UNDER_REVIEW, ComplaintStatus.REJECTED},
    ComplaintStatus.UNDER_REVIEW: {ComplaintStatus.INFO_REQUESTED, ComplaintStatus.CLOSED, ComplaintStatus.REJECTED},
    ComplaintStatus.INFO_REQUESTED: {ComplaintStatus.UNDER_REVIEW, ComplaintStatus.CLOSED, ComplaintStatus.REJECTED},
    ComplaintStatus.CLOSED: set(),
    ComplaintStatus.REJECTED: set(),
}

ALLEGATION_NOTICE = (
    "Cette réclamation est une allégation émise par un opérateur. Elle ne constitue ni une preuve "
    "ni la constatation d'une infraction."
)


class Complaint(models.Model):
    reference = models.CharField(max_length=20, unique=True, editable=False)
    complainant_operator = models.ForeignKey("operators.Operator", on_delete=models.PROTECT, related_name="complaints_filed")
    target_operator = models.ForeignKey("operators.Operator", on_delete=models.PROTECT, related_name="complaints_received")
    filed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    subject = models.CharField("objet", max_length=200)
    description = models.TextField()
    observed_from = models.DateField("comportement observé du", null=True, blank=True)
    observed_to = models.DateField("au", null=True, blank=True)
    status = models.CharField(max_length=20, choices=ComplaintStatus.choices, default=ComplaintStatus.RECEIVED, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "réclamation"
        constraints = [
            models.CheckConstraint(name="complaint_parties_differ", condition=~Q(complainant_operator=F("target_operator"))),
        ]

    def __str__(self):
        return self.reference

    @property
    def allegation_notice(self):
        return ALLEGATION_NOTICE


class ComplaintAttachment(models.Model):
    complaint = models.ForeignKey(Complaint, on_delete=models.CASCADE, related_name="attachments")
    file = models.FileField(upload_to="complaints/", storage=get_private_storage)
    original_filename = models.CharField(max_length=255)
    content_type = models.CharField(max_length=100, blank=True)
    size = models.BigIntegerField(default=0)
    sha256 = models.CharField(max_length=64)
    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    uploaded_at = models.DateTimeField(auto_now_add=True)


class EventType(models.TextChoices):
    FILED = "filed", "Dépôt"
    STATUS_CHANGE = "status_change", "Changement de statut"
    COMPLAINANT_MESSAGE = "complainant_message", "Message du plaignant"
    ARTEC_NOTE = "artec_note", "Note ARTEC"
    ATTACHMENT = "attachment", "Pièce ajoutée"
    DECISION = "decision", "Décision"


class ComplaintEvent(models.Model):
    """Historique en ajout seul."""

    complaint = models.ForeignKey(Complaint, on_delete=models.CASCADE, related_name="events")
    event_type = models.CharField(max_length=25, choices=EventType.choices)
    from_status = models.CharField(max_length=20, blank=True)
    to_status = models.CharField(max_length=20, blank=True)
    note = models.TextField(blank=True)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    visible_to_complainant = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "id"]

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise PermissionError("L'historique est en ajout seul.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise PermissionError("L'historique est en ajout seul.")


class DecisionType(models.TextChoices):
    NO_ACTION = "no_action", "Aucune suite"
    MONITORING = "monitoring", "Surveillance renforcée"
    FORMAL_INQUIRY = "formal_inquiry", "Enquête formelle"
    REFERRED_TO_LEGAL = "referred_to_legal", "Transmission au service juridique"


class ArtecDecision(models.Model):
    """Décision humaine fondée sur des preuves vérifiables. Aucun lien avec une prédiction ML."""

    complaint = models.ForeignKey(Complaint, on_delete=models.PROTECT, related_name="decisions")
    decision_type = models.CharField(max_length=20, choices=DecisionType.choices)
    evidence_summary = models.TextField("résumé des preuves vérifiées")
    decided_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    decided_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-decided_at"]
        constraints = [
            models.CheckConstraint(name="decision_evidence_not_blank", condition=~Q(evidence_summary="")),
        ]
