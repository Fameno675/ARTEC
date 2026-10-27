from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.common.classification import review_reasons
from apps.datasets.models import DataSource, DataSourceType

from . import antispam
from .hashing import content_hash
from .models import FeedbackRating, FeedbackSubmission, Source, ValidationStatus


def public_data_source():
    ds, _ = DataSource.objects.get_or_create(
        name="Formulaire public ARTEC",
        defaults={"source_type": DataSourceType.PUBLIC_FORM, "provenance": "Formulaire public ARTEC",
                  "legal_basis": "Avis volontaires, sans donnée personnelle directe."},
    )
    return ds


@transaction.atomic
def create_public_submission(*, survey, operator, scores, comment, request, device_id):
    qs = FeedbackSubmission.objects.filter(source=Source.PUBLIC_FORM)
    net = antispam.network_hash(request)
    per_hour = antispam.recent_count(qs, "client_hash", net, hours=1)
    today = timezone.localdate()
    reasons = review_reasons(scores, comment, today, check_straight_lining=False)
    if per_hour >= settings.FEEDBACK_NETWORK_REVIEW_PER_HOUR:
        reasons.append("network_rate_high")
    status = ValidationStatus.TO_REVIEW if reasons else ValidationStatus.ACCEPTED
    sub = FeedbackSubmission.objects.create(
        survey_form=survey, operator=operator, collected_at=today, source=Source.PUBLIC_FORM,
        data_source=public_data_source(), dedup_hash=content_hash(operator.code, today, scores, "public_form"),
        content_hash=content_hash(operator.code, today, scores, "public_form"),
        validation_status=status, validation_reasons=reasons, client_hash=net,
        device_hash=antispam.device_hash_for(device_id), comment=comment or "",
    )
    from .models import Criterion
    crit_by_code = {c.code: c for c in Criterion.objects.filter(code__in=scores.keys())}
    FeedbackRating.objects.bulk_create(
        [FeedbackRating(submission=sub, criterion=crit_by_code[code], score=val) for code, val in scores.items()]
    )
    return sub


def purge_client_hashes(days=None):
    """Efface les pseudonymes techniques plus vieux que la durée de conservation (30 jours)."""
    from datetime import timedelta

    days = days or settings.FEEDBACK_CLIENT_HASH_RETENTION_DAYS
    cutoff = timezone.now() - timedelta(days=days)
    return FeedbackSubmission.objects.filter(submitted_at__lt=cutoff).exclude(client_hash="", device_hash="").update(
        client_hash="", device_hash=""
    )
