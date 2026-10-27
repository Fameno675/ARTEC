from datetime import date, timedelta

from django.core.paginator import Paginator
from django.db.models import Count, Q
from django.shortcuts import render
from django.views.decorators.http import require_GET

from apps.analytics import indicators as ind
from apps.audit.models import AuditLog
from apps.common.permissions import artec_required, operator_required
from apps.common.scoring import LIMITATIONS, min_sample
from apps.complaints.models import Complaint
from apps.datasets.models import ImportBatch
from apps.feedback.models import FeedbackSubmission, Source, ValidationStatus
from apps.operators.models import Operator

DISCLAIMER = ("Les comparaisons ci-dessous reposent sur des avis volontaires, pour la période et les volumes indiqués. "
              "Elles ne constituent ni un classement officiel ni une preuve de manquement.")


@require_GET
def home(request):
    return render(request, "public/home.html", {"operators": Operator.objects.active()})


@require_GET
def methodology(request):
    return render(request, "public/methodology.html", {"min_sample": min_sample(), "limitations": LIMITATIONS})


@require_GET
def results(request):
    f = ind.parse_filters(request.GET)
    operators = Operator.objects.active()
    selected = operators.filter(code=f["operator"]) if f["operator"] else operators
    indicators = [ind.compute_indicators(operator=o, start=f["start"], end=f["end"], granularity=f["granularity"]) for o in selected]
    for i, o in zip(indicators, selected):
        i["operator_name"] = o.name
        i["series"] = ind.time_series(operator=o, start=f["start"], end=f["end"], granularity=f["granularity"])
    return render(request, "public/results.html", {
        "filters": f, "indicators": indicators, "operators": operators, "min_sample": min_sample(),
        "limitations": LIMITATIONS, "disclaimer": DISCLAIMER,
    })


@operator_required
@require_GET
def operator_dashboard(request):
    op = request.user.operator
    f = ind.parse_filters(request.GET)
    end = f["end"] or date.today()
    start = f["start"] or end - timedelta(days=90)
    indicators = ind.compute_indicators(operator=op, start=start, end=end, granularity=f["granularity"], include_operator_imports=True)
    return render(request, "operator/dashboard.html", {
        "operator": op, "period": indicators["period"], "indicators": indicators,
        "series": ind.time_series(operator=op, start=start, end=end, granularity=f["granularity"], include_operator_imports=True),
        "recent_imports": ImportBatch.objects.filter(operator=op)[:5], "complaints_by_status": ind.complaints_by_status(op),
        "import_stats": ind.import_stats(op),
    })


@artec_required
@require_GET
def artec_dashboard(request):
    f = ind.parse_filters(request.GET)
    end = f["end"] or date.today()
    start = f["start"] or end - timedelta(days=90)
    comparison = []
    for o in Operator.objects.active():
        i = ind.compute_indicators(operator=o, start=start, end=end, granularity=f["granularity"])
        i["operator_name"] = o.name
        i["series"] = ind.time_series(operator=o, start=start, end=end, granularity=f["granularity"])
        comparison.append(i)
    return render(request, "artec/dashboard.html", {
        "indicators": comparison, "period": {"start": start, "end": end, "granularity": f["granularity"]},
        "counts": ind.submissions_by_operator_and_period(start=start, end=end, granularity=f["granularity"]),
        "import_stats": ind.import_stats(), "ml_summary": ind.ml_summary(),
        "complaints_by_status": ind.complaints_by_status(), "recent_reviews": ind.recent_reviews(),
        "min_sample": min_sample(), "disclaimer": DISCLAIMER,
        "to_review_count": FeedbackSubmission.objects.filter(validation_status=ValidationStatus.TO_REVIEW).count(),
    })


@artec_required
@require_GET
def artec_feedback_list(request):
    qs = FeedbackSubmission.objects.select_related("operator")
    g = request.GET
    for key, field in (("operator", "operator__code"), ("status", "validation_status"), ("source", "source")):
        if g.get(key):
            qs = qs.filter(**{field: g[key]})
    return render(request, "artec/feedback_list.html", {
        "submissions": Paginator(qs, 25).get_page(g.get("page")), "filters": g, "operators": Operator.objects.all(),
        "statuses": ValidationStatus.choices, "sources": Source.choices,
    })


@artec_required
@require_GET
def artec_operators(request):
    ops = Operator.objects.annotate(
        n_accepted=Count("submissions", filter=Q(submissions__validation_status=ValidationStatus.ACCEPTED)),
        n_complaints_filed=Count("complaints_filed", distinct=True), n_complaints_received=Count("complaints_received", distinct=True),
    )
    return render(request, "artec/operators.html", {"operators": ops})


@artec_required
@require_GET
def artec_audit(request):
    qs = AuditLog.objects.select_related("actor")
    if request.GET.get("action"):
        qs = qs.filter(action__startswith=request.GET["action"])
    return render(request, "artec/audit_list.html", {"entries": Paginator(qs, 50).get_page(request.GET.get("page")), "filters": request.GET})
