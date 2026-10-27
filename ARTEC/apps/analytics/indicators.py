"""Indicateurs (backend uniquement, jamais calculés par le ML)."""
from datetime import date

from django.db.models import Avg, Case, Count, IntegerField, StdDev, Sum, Value, When
from django.db.models.functions import TruncDay, TruncMonth, TruncWeek

from apps.common.scoring import LIMITATIONS, NEUTRAL_MIN, POSITIVE_MIN, mean_ci95, min_sample
from apps.complaints.models import Complaint, ComplaintStatus
from apps.datasets.models import ImportBatch, ImportStatus
from apps.feedback.models import FeedbackRating, FeedbackSubmission, Source, ValidationStatus

TRUNC = {"day": TruncDay, "week": TruncWeek, "month": TruncMonth}


def _subs(operator, start, end, include_operator_imports):
    qs = FeedbackSubmission.objects.filter(validation_status=ValidationStatus.ACCEPTED)
    if operator is not None:
        qs = qs.filter(operator=operator)
    if start:
        qs = qs.filter(collected_at__gte=start)
    if end:
        qs = qs.filter(collected_at__lte=end)
    if not include_operator_imports:
        qs = qs.exclude(source=Source.OPERATOR_IMPORT)
    return qs


def compute_indicators(*, operator=None, start=None, end=None, granularity="month", include_operator_imports=False):
    """`include_operator_imports=False` par défaut : exclus des comparaisons inter-opérateurs."""
    subs = _subs(operator, start, end, include_operator_imports)
    n_sub = subs.count()
    sources = dict(subs.values_list("source").annotate(n=Count("id")).order_by())
    ratings = FeedbackRating.objects.filter(submission__in=subs)
    agg = ratings.values("criterion__code").annotate(
        n=Count("id"), mean=Avg("score"), std=StdDev("score", sample=True),
        pos=Sum(Case(When(score__gte=POSITIVE_MIN, then=1), default=0, output_field=IntegerField())),
        neu=Sum(Case(When(score__gte=NEUTRAL_MIN, score__lt=POSITIVE_MIN, then=1), default=0, output_field=IntegerField())),
        neg=Sum(Case(When(score__lt=NEUTRAL_MIN, then=1), default=0, output_field=IntegerField())),
    ).order_by("criterion__code")
    dist = {}
    for code, score, n in ratings.values_list("criterion__code", "score").annotate(n=Count("id")).order_by():
        dist.setdefault(code, {str(i): 0 for i in range(11)})[str(score)] = n
    criteria = []
    for row in agg:
        n = row["n"]
        criteria.append({
            "code": row["criterion__code"], "n_ratings": n,
            "mean": round(float(row["mean"]), 2) if row["mean"] is not None else None,
            "ci95": mean_ci95(n, row["mean"], row["std"]),
            "distribution": dist.get(row["criterion__code"], {}),
            "positive_rate": round(row["pos"] / n, 4), "neutral_rate": round(row["neu"] / n, 4),
            "negative_rate": round(row["neg"] / n, 4),
            "sample_sufficient": n >= min_sample(),
        })
    overall = ratings.aggregate(m=Avg("score"))["m"]
    return {
        "operator": operator.code if operator else None,
        "period": {"start": start.isoformat() if start else None, "end": end.isoformat() if end else None, "granularity": granularity},
        "n_submissions": n_sub, "min_sample": min_sample(), "sample_sufficient": n_sub >= min_sample(),
        "quality_score": round(float(overall), 2) if overall is not None else None,
        "sources": sources, "criteria": criteria,
        "limitations": list(LIMITATIONS) + ([] if n_sub >= min_sample() else
                          [f"Échantillon insuffisant (n={n_sub} < {min_sample()}) : résultat indicatif, non classé."]),
    }


def submissions_by_operator_and_period(*, start=None, end=None, granularity="month", include_operator_imports=False):
    """Nombre d'avis par opérateur et par période."""
    trunc = TRUNC[granularity]
    qs = _subs(None, start, end, include_operator_imports)
    rows = qs.annotate(p=trunc("collected_at")).values("operator__code", "p").annotate(n=Count("id")).order_by("operator__code", "p")
    return [{"operator": r["operator__code"], "period": r["p"].date().isoformat() if hasattr(r["p"], "date") else str(r["p"]), "n": r["n"]} for r in rows]


def time_series(*, operator=None, start=None, end=None, granularity="month", include_operator_imports=False):
    """Évolution temporelle : n avis et quality_score (moyenne des notes) par période."""
    trunc = TRUNC[granularity]
    subs = _subs(operator, start, end, include_operator_imports)
    n_by = {r["p"]: r["n"] for r in subs.annotate(p=trunc("collected_at")).values("p").annotate(n=Count("id")).order_by()}
    rows = FeedbackRating.objects.filter(submission__in=subs).annotate(p=trunc("submission__collected_at")).values("p").annotate(
        m=Avg("score"), nr=Count("id")).order_by("p")
    out = []
    for r in rows:
        key = r["p"]
        out.append({"period": key.date().isoformat() if hasattr(key, "date") else str(key), "n_submissions": n_by.get(key, 0),
                    "n_ratings": r["nr"], "quality_score": round(float(r["m"]), 2),
                    "sample_sufficient": n_by.get(key, 0) >= min_sample()})
    return out


def complaints_by_status(operator=None):
    qs = Complaint.objects.all() if operator is None else Complaint.objects.filter(complainant_operator=operator)
    counts = dict(qs.values_list("status").annotate(n=Count("id")).order_by())
    return {code: counts.get(code, 0) for code, _ in ComplaintStatus.choices}


def import_stats(operator=None):
    qs = ImportBatch.objects.all() if operator is None else ImportBatch.objects.filter(operator=operator)
    a = qs.aggregate(total=Sum("total_rows"), acc=Sum("accepted_rows"), rej=Sum("rejected_rows"), rev=Sum("review_rows"), dup=Sum("duplicate_rows"), n=Count("id"))
    total = a["total"] or 0
    return {"n_batches": a["n"], "total_rows": total, "accepted_rows": a["acc"] or 0, "rejected_rows": a["rej"] or 0,
            "review_rows": a["rev"] or 0, "duplicate_rows": a["dup"] or 0,
            "rejection_rate": round((a["rej"] or 0) / total, 4) if total else 0.0,
            "failed_batches": qs.filter(status=ImportStatus.FAILED).count()}


def ml_summary():
    from .models import MLBatch, MLPrediction, ReviewStatus

    latest = MLBatch.objects.first()
    return {
        "batches_by_status": dict(MLBatch.objects.values_list("status").annotate(n=Count("id")).order_by()),
        "anomalies_flagged": MLPrediction.objects.filter(is_anomaly=True).count(),
        "anomalies_unreviewed": MLPrediction.objects.filter(is_anomaly=True, review_status=ReviewStatus.UNREVIEWED).count(),
        "latest_batch_status": latest.status if latest else None,
        "analysis_pending_or_failed": bool(latest and latest.awaiting_or_failed),
    }


def recent_reviews(limit=10):
    from apps.complaints.models import ArtecDecision

    from .models import AnomalyReview

    return {"anomaly_reviews": list(AnomalyReview.objects.select_related("reviewer", "prediction")[:limit]),
            "decisions": list(ArtecDecision.objects.select_related("complaint", "decided_by")[:limit])}


def parse_filters(params):
    """Lit start / end / granularity / operator depuis une query string, avec valeurs sûres par défaut."""
    def d(v):
        try:
            return date.fromisoformat(v) if v else None
        except ValueError:
            return None

    g = params.get("granularity", "month")
    return {"start": d(params.get("start")), "end": d(params.get("end")), "granularity": g if g in TRUNC else "month",
            "operator": params.get("operator", "")}
