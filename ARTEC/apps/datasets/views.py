from django.core.paginator import Paginator
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_GET, require_http_methods

from apps.audit.services import log
from apps.common.permissions import artec_required, operator_required

from .forms import DataSourceForm, ImportForm
from .importer import error_report_csv, process_import, template_csv
from .models import DataSource, DataSourceType, ImportBatch, RowStatus


def _page(request, qs, per=25):
    return Paginator(qs, per).get_page(request.GET.get("page"))


def _operator_source(operator):
    ds, _ = DataSource.objects.get_or_create(
        name=f"Import fichier — {operator.name}",
        defaults={"source_type": DataSourceType.OPERATOR_FILE, "provenance": f"Fichiers fournis par {operator.name}",
                  "usage_limits": "Données déclaratives de l'opérateur ; exclues par défaut des comparaisons inter-opérateurs."},
    )
    return ds


def _detail_context(request, batch):
    rows = batch.rows.exclude(status=RowStatus.ACCEPTED)
    status = request.GET.get("status")
    if status in (RowStatus.REJECTED, RowStatus.TO_REVIEW):
        rows = rows.filter(status=status)
    return {"batch": batch, "summary": batch.error_summary, "row_errors": _page(request, rows),
            "filters": {"status": status or ""}}


# ---- opérateur : périmètre = request.user.operator, jamais d'identifiant d'opérateur dans l'URL ----
@operator_required
@require_GET
def operator_import_list(request):
    qs = ImportBatch.objects.filter(operator=request.user.operator)
    return render(request, "operator/import_list.html", {"batches": _page(request, qs)})


@operator_required
@require_http_methods(["GET", "POST"])
def operator_import_create(request):
    form = ImportForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        op = request.user.operator
        batch = process_import(uploaded_file=form.cleaned_data["file"], user=request.user,
                               data_source=_operator_source(op), operator_scope=op)
        return redirect("operator:import_detail", pk=batch.pk)
    return render(request, "operator/import_create.html", {"form": form})


@operator_required
@require_GET
def operator_import_detail(request, pk):
    batch = get_object_or_404(ImportBatch, pk=pk, operator=request.user.operator)
    return render(request, "operator/import_detail.html", _detail_context(request, batch))


@operator_required
@require_GET
def operator_import_errors(request, pk):
    batch = get_object_or_404(ImportBatch, pk=pk, operator=request.user.operator)
    return _csv_response(error_report_csv(batch), f"erreurs-{batch.pk}.csv")


@operator_required
@require_GET
def operator_import_template(request):
    return _csv_response(template_csv(for_operator=True), "modele-import-artec.csv")


def _csv_response(text, filename):
    resp = HttpResponse(text, content_type="text/csv; charset=utf-8")
    resp["Content-Disposition"] = f'attachment; filename="{filename}"'
    resp["X-Content-Type-Options"] = "nosniff"
    return resp


# ---- ARTEC ----
@artec_required
@require_GET
def artec_import_list(request):
    qs = ImportBatch.objects.select_related("data_source", "operator", "uploaded_by")
    if request.GET.get("status"):
        qs = qs.filter(status=request.GET["status"])
    return render(request, "artec/import_list.html", {"batches": _page(request, qs), "filters": request.GET})


@artec_required
@require_http_methods(["GET", "POST"])
def artec_import_create(request):
    form = ImportForm(request.POST or None, request.FILES or None, artec=True)
    if request.method == "POST" and form.is_valid():
        batch = process_import(uploaded_file=form.cleaned_data["file"], user=request.user,
                               data_source=form.cleaned_data["data_source"], operator_scope=None)
        return redirect("artec:import_detail", pk=batch.pk)
    return render(request, "artec/import_create.html", {"form": form})


@artec_required
@require_GET
def artec_import_detail(request, pk):
    batch = get_object_or_404(ImportBatch, pk=pk)
    return render(request, "artec/import_detail.html", _detail_context(request, batch))


@artec_required
@require_GET
def artec_import_errors(request, pk):
    batch = get_object_or_404(ImportBatch, pk=pk)
    return _csv_response(error_report_csv(batch), f"erreurs-{batch.pk}.csv")


@artec_required
@require_GET
def artec_import_template(request):
    return _csv_response(template_csv(for_operator=False), "modele-import-artec-admin.csv")


@artec_required
@require_GET
def artec_source_list(request):
    return render(request, "artec/source_list.html", {"sources": _page(request, DataSource.objects.all())})


@artec_required
@require_http_methods(["GET", "POST"])
def artec_source_create(request):
    form = DataSourceForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        src = form.save(commit=False)
        src.created_by = request.user
        src.save()
        log(request.user, "datasource.created", src, source_type=src.source_type)
        return redirect("artec:source_list")
    return render(request, "artec/source_form.html", {"form": form})
