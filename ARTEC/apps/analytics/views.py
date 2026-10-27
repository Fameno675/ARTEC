from datetime import date, timedelta

from django import forms
from django.contrib import messages
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from apps.common.permissions import artec_required
from apps.operators.models import Operator

from . import recommendations as reco
from . import services
from .models import MLBatch, MLPrediction, ReviewStatus


class BatchForm(forms.Form):
    operator = forms.ModelChoiceField(queryset=Operator.objects.all(), required=False, empty_label="Tous les opérateurs")
    start = forms.DateField(widget=forms.DateInput(attrs={"type": "date"}), label="Début")
    end = forms.DateField(widget=forms.DateInput(attrs={"type": "date"}), label="Fin")

    def clean(self):
        c = super().clean()
        if c.get("start") and c.get("end") and c["end"] < c["start"]:
            self.add_error("end", "La fin précède le début.")
        return c


class ReviewForm(forms.Form):
    outcome = forms.ChoiceField(choices=[c for c in ReviewStatus.choices if c[0] != ReviewStatus.UNREVIEWED])
    notes = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 2}))


REASONS_LEGEND = {
    "straight_lining": "Toutes les notes sont identiques.",
    "extreme_scores_only": "Uniquement des notes extrêmes (0 ou 10).",
    "isolation_forest_outlier": "Combinaison de notes atypique par rapport au lot.",
    "uniform_extreme_ratings": "Toutes les notes sont identiques et extrêmes.",
    "extreme_only_ratings": "Notes exclusivement extrêmes (0 ou 10), non identiques.",
    "statistical_outlier": "Combinaison de variables statistiquement inhabituelle.",
    "repeated_comment": "Commentaire identique répété dans le lot.",
}


@artec_required
@require_http_methods(["GET", "POST"])
def mlbatch_list(request):
    today = date.today()
    form = BatchForm(request.POST or None, initial={"start": today - timedelta(days=90), "end": today})
    if request.method == "POST" and form.is_valid():
        batch = services.create_batch(requested_by=request.user, operator=form.cleaned_data["operator"],
                                      start=form.cleaned_data["start"], end=form.cleaned_data["end"])
        services.execute_batch(batch)
        return redirect("artec:mlbatch_detail", pk=batch.pk)
    return render(request, "artec/mlbatch_list.html", {"batches": Paginator(MLBatch.objects.all(), 25).get_page(request.GET.get("page")), "form": form})


@artec_required
@require_GET
def mlbatch_detail(request, pk):
    batch = get_object_or_404(MLBatch, pk=pk)
    preds = batch.predictions.select_related("submission__operator").prefetch_related("submission__ratings__criterion")
    if request.GET.get("anomalies") == "1":
        preds = preds.filter(is_anomaly=True)
    return render(request, "artec/mlbatch_detail.html", {
        "batch": batch, "predictions": Paginator(preds.order_by("-anomaly_score"), 25).get_page(request.GET.get("page")),
        "reasons_legend": REASONS_LEGEND, "review_form": ReviewForm(),
    })


@artec_required
@require_POST
def prediction_review(request, pk):
    pred = get_object_or_404(MLPrediction, pk=pk)
    form = ReviewForm(request.POST)
    if form.is_valid():
        services.review_prediction(prediction=pred, reviewer=request.user, **form.cleaned_data)
        messages.success(request, "Examen enregistré.")
    return redirect("artec:mlbatch_detail", pk=pred.batch_id)


@artec_required
@require_GET
def recommendations(request):
    try:
        days = int(request.GET.get("jours", reco.DEFAULT_WINDOW_DAYS))
    except ValueError:
        days = reco.DEFAULT_WINDOW_DAYS
    if days not in reco.WINDOWS:
        days = reco.DEFAULT_WINDOW_DAYS
    return render(request, "artec/recommendations.html", {"reco": reco.compute_recommendations(window_days=days), "windows": reco.WINDOWS})
