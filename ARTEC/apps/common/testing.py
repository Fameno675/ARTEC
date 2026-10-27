"""Fabriques de test partagées."""
import io
import itertools
from datetime import date, timedelta

from django.core.files.uploadedfile import SimpleUploadedFile

from apps.accounts.models import Role, User
from apps.feedback.models import Criterion, FeedbackRating, FeedbackSubmission, Source, ValidationStatus
from apps.operators.models import Operator

PASSWORD = "Str0ng-Passw0rd-xyz"
_counter = itertools.count(1)


def op(code):
    return Operator.objects.get(code=code)


def make_user(role, operator_code=None, email=None):
    email = email or f"u{next(_counter)}@example.mg"
    return User.objects.create_user(
        email=email, password=PASSWORD, full_name="Test User", role=role,
        operator=op(operator_code) if operator_code else None, is_staff=(role == Role.TECH_ADMIN),
    )


def operator_user(code="orange"):
    return make_user(Role.OPERATOR, code)


def artec_user():
    return make_user(Role.ARTEC_ADMIN)


def tech_user():
    return make_user(Role.TECH_ADMIN)


def make_submission(operator_code, scores, *, collected_at=None, source=Source.PUBLIC_FORM,
                    status=ValidationStatus.ACCEPTED):
    sub = FeedbackSubmission.objects.create(
        operator=op(operator_code), collected_at=collected_at or date.today(), source=source, validation_status=status,
        dedup_hash=f"h{next(_counter)}",
    )
    codes = {c.code: c for c in Criterion.objects.all()}
    FeedbackRating.objects.bulk_create([FeedbackRating(submission=sub, criterion=codes[k], score=v) for k, v in scores.items()])
    return sub


def csv_upload(text, name="data.csv"):
    return SimpleUploadedFile(name, text.encode("utf-8"), content_type="text/csv")


CSV_HEADER = "external_id,operator_code,collected_at,score_mobile_data_speed,score_call_audio_quality,score_customer_service,comment"


def recent_date(days_ago=3):
    return (date.today() - timedelta(days=days_ago)).isoformat()


def xlsx_upload(rows, header=None, name="data.xlsx", sheet="feedback"):
    import openpyxl

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = sheet
    ws.append(header or CSV_HEADER.split(","))
    for r in rows:
        ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return SimpleUploadedFile(name, buf.getvalue(),
                              content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
