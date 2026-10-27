from django.contrib import messages
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from apps.common.permissions import artec_required, operator_required

from . import services
from .forms import AttachmentForm, ComplaintForm, DecisionForm, MessageForm, StatusForm
from .models import ALLEGATION_NOTICE, Complaint, ComplaintAttachment, ComplaintStatus


def _page(request, qs):
    return Paginator(qs, 25).get_page(request.GET.get("page"))


def _own(request, reference):
    """Queryset filtré : une référence d'un autre opérateur donne 404."""
    return get_object_or_404(Complaint, reference=reference, complainant_operator=request.user.operator)


def _errors(request, exc):
    for m in (exc.messages if isinstance(exc, ValidationError) else [str(exc)]):
        messages.error(request, m)


# ---- opérateur ----
@operator_required
@require_GET
def operator_complaint_list(request):
    qs = Complaint.objects.filter(complainant_operator=request.user.operator).select_related("target_operator")
    if request.GET.get("status"):
        qs = qs.filter(status=request.GET["status"])
    return render(request, "operator/complaint_list.html", {"complaints": _page(request, qs), "filters": request.GET,
                                                           "statuses": ComplaintStatus.choices})


@operator_required
@require_http_methods(["GET", "POST"])
def operator_complaint_create(request):
    form = ComplaintForm(request.POST or None, user=request.user)
    if request.method == "POST" and form.is_valid():
        try:
            c = services.create_complaint(user=request.user, **form.cleaned_data)
        except ValidationError as exc:
            form.add_error(None, exc)
        else:
            return redirect("operator:complaint_detail", reference=c.reference)
    return render(request, "operator/complaint_create.html", {"form": form, "allegation_notice": ALLEGATION_NOTICE})


@operator_required
@require_GET
def operator_complaint_detail(request, reference):
    c = _own(request, reference)
    return render(request, "operator/complaint_detail.html", {
        "complaint": c, "events": c.events.filter(visible_to_complainant=True), "attachments": c.attachments.all(),
        "allegation_notice": ALLEGATION_NOTICE, "attach_form": AttachmentForm(), "message_form": MessageForm(),
    })


@operator_required
@require_POST
def operator_complaint_attach(request, reference):
    c = _own(request, reference)
    form = AttachmentForm(request.POST, request.FILES)
    if form.is_valid():
        try:
            services.add_attachment(complaint=c, user=request.user, uploaded=form.cleaned_data["file"])
            messages.success(request, "Pièce ajoutée.")
        except ValidationError as exc:
            _errors(request, exc)
    else:
        messages.error(request, "Fichier manquant.")
    return redirect("operator:complaint_detail", reference=reference)


@operator_required
@require_POST
def operator_complaint_reply(request, reference):
    c = _own(request, reference)
    form = MessageForm(request.POST)
    if form.is_valid():
        try:
            services.add_message(complaint=c, user=request.user, note=form.cleaned_data["note"])
            messages.success(request, "Message envoyé.")
        except ValidationError as exc:
            _errors(request, exc)
    return redirect("operator:complaint_detail", reference=reference)


@operator_required
@require_GET
def operator_attachment_download(request, reference, pk):
    c = _own(request, reference)
    att = get_object_or_404(ComplaintAttachment, pk=pk, complaint=c)
    return _download(att)


def _download(att):
    try:
        resp = FileResponse(att.file.open("rb"), as_attachment=True, filename=att.original_filename)
    except FileNotFoundError:
        raise Http404
    resp["X-Content-Type-Options"] = "nosniff"
    return resp


# ---- ARTEC ----
@artec_required
@require_GET
def artec_complaint_list(request):
    qs = Complaint.objects.select_related("complainant_operator", "target_operator")
    for key, field in (("status", "status"), ("complainant", "complainant_operator__code"), ("target", "target_operator__code")):
        if request.GET.get(key):
            qs = qs.filter(**{field: request.GET[key]})
    return render(request, "artec/complaint_list.html", {"complaints": _page(request, qs), "filters": request.GET,
                                                        "statuses": ComplaintStatus.choices})


@artec_required
@require_GET
def artec_complaint_detail(request, reference):
    c = get_object_or_404(Complaint, reference=reference)
    return render(request, "artec/complaint_detail.html", {
        "complaint": c, "events": c.events.all(), "attachments": c.attachments.all(), "decisions": c.decisions.all(),
        "allegation_notice": ALLEGATION_NOTICE, "status_form": StatusForm(), "decision_form": DecisionForm(),
    })


@artec_required
@require_POST
def artec_complaint_status(request, reference):
    c = get_object_or_404(Complaint, reference=reference)
    form = StatusForm(request.POST)
    if form.is_valid():
        try:
            services.change_status(complaint=c, user=request.user, new_status=form.cleaned_data["status"],
                                   note=form.cleaned_data["note"], visible=form.cleaned_data["visible_to_complainant"])
            messages.success(request, "Statut mis à jour.")
        except ValidationError as exc:
            _errors(request, exc)
    return redirect("artec:complaint_detail", reference=reference)


@artec_required
@require_POST
def artec_complaint_decision(request, reference):
    c = get_object_or_404(Complaint, reference=reference)
    form = DecisionForm(request.POST)
    if form.is_valid():
        try:
            services.record_decision(complaint=c, user=request.user, **form.cleaned_data)
            messages.success(request, "Décision enregistrée.")
        except ValidationError as exc:
            _errors(request, exc)
    return redirect("artec:complaint_detail", reference=reference)


@artec_required
@require_GET
def artec_attachment_download(request, reference, pk):
    c = get_object_or_404(Complaint, reference=reference)
    return _download(get_object_or_404(ComplaintAttachment, pk=pk, complaint=c))
