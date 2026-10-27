from django.core.paginator import Paginator
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from apps.audit.services import log
from apps.common.permissions import artec_required

from . import antispam
from .forms import PublicFeedbackForm, SurveyAdminForm
from .models import FeedbackSubmission, SurveyForm, ValidationStatus
from .services import create_public_submission


@require_GET
def survey_list(request):
    now = timezone.now()
    surveys = [s for s in SurveyForm.objects.filter(is_active=True) if s.is_open(now)]
    return render(request, "public/survey_list.html", {"surveys": surveys})


@require_http_methods(["GET", "POST"])
def survey_detail(request, slug):
    survey = get_object_or_404(SurveyForm, slug=slug)
    if not survey.is_open():
        raise Http404("Ce sondage n'est pas disponible.")

    device_id = antispam.existing_device_id(request)
    new_cookie = device_id is None
    if new_cookie:
        device_id = antispam.new_device_id()

    if request.method == "POST":
        from django.conf import settings

        from .models import Source
        net = antispam.network_hash(request)
        recent = antispam.recent_count(
            FeedbackSubmission.objects.filter(source=Source.PUBLIC_FORM), "client_hash", net, hours=1
        )
        if recent >= settings.FEEDBACK_NETWORK_BLOCK_PER_HOUR:
            return render(request, "public/too_many.html", status=429)

        form = PublicFeedbackForm(request.POST, survey=survey)
        if form.data.get("website"):  # honeypot : réponse neutre, rien n'est enregistré
            return redirect("public:survey_thanks", slug=slug)
        ok, code = antispam.check_form_token(form.data.get("form_ts"))
        if form.is_valid():
            if not ok:
                form.add_error(None, "Formulaire envoyé trop vite, veuillez réessayer." if code == "too_fast"
                               else "Le formulaire a expiré, rechargez la page.")
            elif not new_cookie and antispam.recent_count(
                FeedbackSubmission.objects.filter(
                    source=Source.PUBLIC_FORM, survey_form=survey, operator=form.cleaned_data["operator"]
                ),
                "device_hash", antispam.device_hash_for(device_id), hours=settings.FEEDBACK_DEVICE_WINDOW_HOURS,
            ):
                form.add_error("operator", "Vous avez déjà évalué cet opérateur pour ce sondage aujourd'hui.")
        if form.is_valid():
            create_public_submission(
                survey=survey, operator=form.cleaned_data["operator"], scores=form.scores(),
                comment=form.cleaned_data.get("comment", ""), request=request, device_id=device_id,
            )
            response = redirect("public:survey_thanks", slug=slug)
            antispam.set_device_cookie(response, device_id)
            return response
    else:
        form = PublicFeedbackForm(survey=survey, initial={"form_ts": antispam.make_form_token()})

    if request.method == "POST":
        form.data = form.data.copy()
        form.data["form_ts"] = antispam.make_form_token()
    response = render(request, "public/survey_detail.html", {
        "survey": survey, "form": form, "criteria_fields": form.criteria_fields,
        "operators": form.fields["operator"].queryset, "scale": {"min": 0, "max": 10},
    })
    if new_cookie:
        antispam.set_device_cookie(response, device_id)
    return response


@require_GET
def survey_thanks(request, slug):
    survey = get_object_or_404(SurveyForm, slug=slug)
    return render(request, "public/survey_thanks.html", {"survey": survey})


# ----- ARTEC : gestion des sondages et validation des avis -----
@artec_required
@require_GET
def artec_survey_list(request):
    return render(request, "artec/survey_list.html", {"surveys": SurveyForm.objects.all()})


@artec_required
@require_http_methods(["GET", "POST"])
def artec_survey_edit(request, pk=None):
    survey = get_object_or_404(SurveyForm, pk=pk) if pk else None
    form = SurveyAdminForm(request.POST or None, instance=survey)
    if request.method == "POST" and form.is_valid():
        obj = form.save(commit=False)
        if survey is None:
            obj.created_by = request.user
        obj.save()
        form.save()
        log(request.user, "survey.saved", obj, created=survey is None)
        return redirect("artec:survey_list")
    return render(request, "artec/survey_form.html", {"form": form, "survey": survey})


@artec_required
@require_POST
def artec_feedback_validate(request, pk):
    sub = get_object_or_404(FeedbackSubmission, pk=pk)
    decision = request.POST.get("decision")
    if sub.validation_status != ValidationStatus.TO_REVIEW or decision not in ("accept", "reject"):
        return HttpResponse(status=400)
    old = sub.validation_status
    sub.validation_status = ValidationStatus.ACCEPTED if decision == "accept" else ValidationStatus.REJECTED
    sub.save(update_fields=["validation_status"])
    log(request.user, "feedback.reviewed", sub, decision=decision, previous=old)
    return redirect(request.META.get("HTTP_REFERER") or "artec:feedback_list")
