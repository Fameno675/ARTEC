import os

from django.conf import settings
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.files.base import ContentFile
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.accounts.models import Role
from apps.audit.services import log
from apps.common.utils import clean_text, sha256_bytes

from .models import (ALLOWED_TRANSITIONS, ArtecDecision, Complaint, ComplaintAttachment, ComplaintEvent,
                     ComplaintStatus, EventType)

ALLOWED_EXTENSIONS = {".pdf": "application/pdf", ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                      ".csv": "text/csv", ".txt": "text/plain", ".xlsx": None}
MAGIC = {".pdf": b"%PDF", ".png": b"\x89PNG", ".jpg": b"\xff\xd8\xff", ".jpeg": b"\xff\xd8\xff", ".xlsx": b"PK"}


def _fresh(complaint):
    """Relit la réclamation en base avec verrou : le statut en mémoire peut être périmé."""
    return Complaint.objects.select_for_update().get(pk=complaint.pk)


def _next_reference():
    year = timezone.localdate().year
    prefix = f"REC-{year}-"
    last = Complaint.objects.filter(reference__startswith=prefix).order_by("-reference").values_list("reference", flat=True).first()
    n = int(last.rsplit("-", 1)[1]) + 1 if last else 1
    return f"{prefix}{n:04d}"


def create_complaint(*, user, target_operator, subject, description, observed_from=None, observed_to=None):
    if user.role != Role.OPERATOR or not user.operator_id:
        raise PermissionDenied
    if target_operator.pk == user.operator_id:
        raise ValidationError("Un opérateur ne peut pas déposer une réclamation contre lui-même.")
    for _ in range(5):  # réessai en cas de collision de référence concurrente
        try:
            with transaction.atomic():
                c = Complaint.objects.create(
                    reference=_next_reference(), complainant_operator=user.operator, target_operator=target_operator,
                    filed_by=user, subject=subject, description=description, observed_from=observed_from, observed_to=observed_to,
                )
                ComplaintEvent.objects.create(complaint=c, event_type=EventType.FILED, to_status=c.status, actor=user,
                                              note="Réclamation déposée.", visible_to_complainant=True)
                log(user, "complaint.filed", c, target=target_operator.code)
                return c
        except IntegrityError:
            continue
    raise RuntimeError("Impossible de générer une référence de réclamation.")


@transaction.atomic
def change_status(*, complaint, user, new_status, note="", visible=True):
    if user.role != Role.ARTEC_ADMIN:
        raise PermissionDenied
    complaint = Complaint.objects.select_for_update().get(pk=complaint.pk)
    if new_status not in ALLOWED_TRANSITIONS.get(complaint.status, set()):
        raise ValidationError(f"Transition interdite : {complaint.status} → {new_status}.")
    old = complaint.status
    complaint.status = new_status
    complaint.save(update_fields=["status", "updated_at"])
    ComplaintEvent.objects.create(complaint=complaint, event_type=EventType.STATUS_CHANGE, from_status=old, to_status=new_status,
                                  note=clean_text(note), actor=user, visible_to_complainant=visible)
    log(user, "complaint.status_changed", complaint, from_status=old, to_status=new_status)
    return complaint


@transaction.atomic
def add_message(*, complaint, user, note):
    """Message du plaignant (ex. réponse à une demande d'informations)."""
    complaint = _fresh(complaint)
    if user.role != Role.OPERATOR or user.operator_id != complaint.complainant_operator_id:
        raise PermissionDenied
    if complaint.status in (ComplaintStatus.CLOSED, ComplaintStatus.REJECTED):
        raise ValidationError("Cette réclamation est clôturée.")
    note = clean_text(note)
    if not note:
        raise ValidationError("Le message est vide.")
    ev = ComplaintEvent.objects.create(complaint=complaint, event_type=EventType.COMPLAINANT_MESSAGE, note=note,
                                       actor=user, visible_to_complainant=True)
    return ev


@transaction.atomic
def add_attachment(*, complaint, user, uploaded):
    complaint = _fresh(complaint)
    if user.role == Role.OPERATOR and user.operator_id != complaint.complainant_operator_id:
        raise PermissionDenied
    if user.role not in (Role.OPERATOR, Role.ARTEC_ADMIN):
        raise PermissionDenied
    if complaint.status in (ComplaintStatus.CLOSED, ComplaintStatus.REJECTED):
        raise ValidationError("Cette réclamation est clôturée.")
    name = clean_text(os.path.basename(uploaded.name))[:255]
    ext = os.path.splitext(name)[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise ValidationError("Type de fichier refusé (PDF, PNG, JPG, CSV, TXT, XLSX).")
    if uploaded.size > settings.COMPLAINT_MAX_ATTACHMENT_BYTES:
        raise ValidationError("Pièce trop volumineuse.")
    data = uploaded.read()
    if ext in MAGIC and not data.startswith(MAGIC[ext]):
        raise ValidationError("Le contenu du fichier ne correspond pas à son extension.")
    att = ComplaintAttachment(complaint=complaint, original_filename=name, size=len(data), sha256=sha256_bytes(data),
                              content_type=ALLOWED_EXTENSIONS[ext] or "application/octet-stream", uploaded_by=user)
    att.file.save(f"{sha256_bytes(data)[:16]}{ext}", ContentFile(data), save=False)
    att.save()
    ComplaintEvent.objects.create(complaint=complaint, event_type=EventType.ATTACHMENT, note=name, actor=user,
                                  visible_to_complainant=True)
    log(user, "complaint.attachment_added", complaint, filename=name, sha256=att.sha256)
    return att


@transaction.atomic
def record_decision(*, complaint, user, decision_type, evidence_summary):
    if user.role != Role.ARTEC_ADMIN:
        raise PermissionDenied
    complaint = _fresh(complaint)
    evidence = clean_text(evidence_summary)
    if len(evidence) < 20:
        raise ValidationError("Le résumé des preuves vérifiables est obligatoire (20 caractères minimum).")
    if complaint.status != ComplaintStatus.UNDER_REVIEW:
        raise ValidationError("Une décision n'est possible que pour une réclamation en cours d'examen.")
    d = ArtecDecision.objects.create(complaint=complaint, decision_type=decision_type, evidence_summary=evidence, decided_by=user)
    ComplaintEvent.objects.create(complaint=complaint, event_type=EventType.DECISION, note=f"{d.get_decision_type_display()}",
                                  actor=user, visible_to_complainant=False)
    log(user, "complaint.decision", complaint, decision=decision_type)
    return d
