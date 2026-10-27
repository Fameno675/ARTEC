"""Recommandations réglementaires (aide à la décision) calculées EN DIRECT sur une fenêtre récente.

Principe : ARTEC voit, à chaque consultation, la situation des opérateurs sur les N derniers jours (7/30/90) ;
ce ne sont pas des données vieilles d'un mois qui sont traitées. Le ML intervient en amont : les avis dont
l'anomalie a été CONFIRMÉE par un agent sont exclus du calcul, et les alertes non examinées rendent la
recommandation « provisoire ». Une recommandation n'est jamais une sanction : la décision reste humaine
(instruction via les réclamations, journal d'audit).
"""
from datetime import date, timedelta

from django.db.models import Avg, Case, Count, IntegerField, StdDev, Sum, When

from apps.common.scoring import NEUTRAL_MIN, POSITIVE_MIN, mean_ci95, min_sample
from apps.complaints.models import Complaint
from apps.feedback.models import FeedbackRating, FeedbackSubmission, Source, ValidationStatus
from apps.operators.models import Operator

from .models import MLPrediction, ReviewStatus

WINDOWS = (7, 30, 90)
DEFAULT_WINDOW_DAYS = 30

# Seuils (échelle 0-10), documentés dans la page Méthodologie et modifiables ici en un seul endroit.
SANCTION_MEAN_MAX = 4.0     # moyenne < 4 ET borne haute de l'IC95 < 5 : insatisfaction nette et statistiquement établie
WARNING_MEAN_MAX = 5.5      # moyenne < 5,5 : avertissement
LOWEST_RANK_WARNING_MAX = 6.0  # dernier du classement avec moyenne < 6 : avertissement
FLAGGED_SHARE_PROVISIONAL = 0.10   # >= 10 % d'avis signalés par le ML et non examinés : résultat provisoire
ML_COVERAGE_MIN = 0.5       # < 50 % des avis analysés par le ML : résultat provisoire

CONGRATULATE, WARNING, SANCTION_REVIEW, COMPLIANT, INSUFFICIENT = (
    "reco_congratulate", "reco_warning", "reco_sanction_review", "reco_compliant", "reco_insufficient")
LABELS = {
    CONGRATULATE: "Félicitations",
    WARNING: "Avertissement",
    SANCTION_REVIEW: "Instruction de sanction à envisager",
    COMPLIANT: "Conforme — aucune action",
    INSUFFICIENT: "Échantillon insuffisant",
}


def _stats(operator, start, end):
    confirmed = MLPrediction.objects.filter(review_status=ReviewStatus.CONFIRMED).values("submission_id")
    subs = (FeedbackSubmission.objects
            .filter(operator=operator, validation_status=ValidationStatus.ACCEPTED, collected_at__gte=start, collected_at__lte=end)
            .exclude(source=Source.OPERATOR_IMPORT)      # les imports de l'opérateur lui-même ne servent pas à le juger
            .exclude(id__in=confirmed))                  # anomalies confirmées par un humain : exclues
    n = subs.count()
    agg = FeedbackRating.objects.filter(submission__in=subs).aggregate(
        mean=Avg("score"), std=StdDev("score", sample=True), n=Sum(1),
        neg=Sum(Case(When(score__lt=NEUTRAL_MIN, then=1), default=0, output_field=IntegerField())),
        pos=Sum(Case(When(score__gte=POSITIVE_MIN, then=1), default=0, output_field=IntegerField())),
    ) if n else {"mean": None, "std": None, "n": 0, "neg": 0, "pos": 0}
    n_ratings = agg["n"] or 0
    analysed = MLPrediction.objects.filter(submission__in=subs).values("submission_id").distinct().count() if n else 0
    flagged = (MLPrediction.objects.filter(submission__in=subs, is_anomaly=True, review_status=ReviewStatus.UNREVIEWED)
               .values("submission_id").distinct().count() if n else 0)
    mean = round(float(agg["mean"]), 2) if agg["mean"] is not None else None
    return {
        "operator": operator, "n_submissions": n, "n_ratings": n_ratings, "mean": mean,
        "ci95": mean_ci95(n_ratings, agg["mean"], agg["std"]),
        "negative_rate": round(agg["neg"] / n_ratings, 4) if n_ratings else None,
        "positive_rate": round(agg["pos"] / n_ratings, 4) if n_ratings else None,
        "ml_analysed": analysed, "ml_flagged_unreviewed": flagged,
        "complaints_received": Complaint.objects.filter(target_operator=operator, created_at__date__gte=start,
                                                        created_at__date__lte=end).count(),
    }


def compute_recommendations(*, window_days=DEFAULT_WINDOW_DAYS, today=None):
    today = today or date.today()
    start = today - timedelta(days=window_days - 1)
    rows = [_stats(o, start, today) for o in Operator.objects.active()]
    threshold = min_sample()
    eligible = [r for r in rows if r["n_submissions"] >= threshold and r["mean"] is not None]
    eligible.sort(key=lambda r: r["mean"], reverse=True)
    for rank, r in enumerate(eligible, start=1):
        r["rank"] = rank

    for r in rows:
        r.setdefault("rank", None)
        r["min_sample"] = threshold
        r["verdict"], r["explanation"] = _verdict(r, eligible)
        notes = []
        if r["n_submissions"] and r["ml_analysed"] / r["n_submissions"] < ML_COVERAGE_MIN:
            notes.append("Moins de la moitié des avis de la fenêtre ont été analysés par le moteur ML : lancez une analyse.")
        if r["n_submissions"] and r["ml_flagged_unreviewed"] / r["n_submissions"] >= FLAGGED_SHARE_PROVISIONAL:
            notes.append(f"{r['ml_flagged_unreviewed']} avis signalés atypiques par le ML n'ont pas été examinés : résultat provisoire.")
        r["provisional_notes"] = notes
        r["provisional"] = bool(notes) and r["verdict"] != INSUFFICIENT
        r["verdict_label"] = LABELS[r["verdict"]]
    rows.sort(key=lambda r: (r["rank"] is None, r["rank"] or 0, r["operator"].code))
    return {"window_days": window_days, "start": start, "end": today, "operators": rows, "min_sample": threshold,
            "labels": LABELS}


def _verdict(r, eligible):
    if r["rank"] is None:
        return INSUFFICIENT, (f"{r['n_submissions']} avis acceptés sur la fenêtre ; il en faut au moins {r['min_sample']} "
                              "pour émettre une recommandation.")
    mean, ci = r["mean"], r["ci95"]
    if mean < SANCTION_MEAN_MAX and ci and ci[1] < NEUTRAL_MIN:
        return SANCTION_REVIEW, (f"Note moyenne {mean}/10, intervalle de confiance à 95 % entièrement sous {NEUTRAL_MIN} : "
                                 "insatisfaction nette. Instruction à ouvrir avec examen des preuves.")
    if mean < WARNING_MEAN_MAX:
        return WARNING, f"Note moyenne {mean}/10, sous le seuil de {WARNING_MEAN_MAX}."
    if len(eligible) > 1 and r["rank"] == len(eligible) and mean < LOWEST_RANK_WARNING_MAX:
        return WARNING, f"Dernier du classement avec {mean}/10 (seuil {LOWEST_RANK_WARNING_MAX})."
    if r["rank"] == 1 and mean >= POSITIVE_MIN:
        others = [o["mean"] for o in eligible if o is not r]
        if not others or (ci and ci[0] > sum(others) / len(others)):
            return CONGRATULATE, (f"Meilleure note ({mean}/10) et nettement au-dessus de la moyenne des autres opérateurs."
                                  if others else f"Seul opérateur évaluable, avec {mean}/10.")
    return COMPLIANT, f"Note moyenne {mean}/10 : dans la norme de la période."
