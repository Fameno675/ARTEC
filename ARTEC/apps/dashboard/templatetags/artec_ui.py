"""Balises de gabarit du frontend ARTEC. Lecture seule : aucune écriture en base."""
from django import template
from django.utils.html import format_html

from apps.datasets.importer import ERROR_MESSAGES
from apps.feedback.models import Criterion, CriterionCategory
from apps.operators.models import Operator

register = template.Library()

_CATEGORY_LABELS = dict(CriterionCategory.choices)

EXTRA_REASON_LABELS = {
    "network_rate_high": "Volume élevé d'avis depuis un même réseau : à examiner.",
}

# statut -> (variante, icône Bootstrap Icons). Statuts de tous les domaines du backend.
BADGES = {
    # avis
    "accepted": ("success", "check-circle-fill"), "to_review": ("warning", "eye-fill"),
    "rejected": ("danger", "x-circle-fill"), "pending": ("neutral", "hourglass-split"),
    # imports
    "committed": ("success", "check-circle-fill"), "failed": ("danger", "x-octagon-fill"),
    "uploaded": ("info", "cloud-arrow-up-fill"), "validated": ("info", "patch-check-fill"), "cancelled": ("neutral", "slash-circle"),
    # réclamations
    "received": ("info", "inbox-fill"), "under_review": ("warning", "search"), "info_requested": ("warning", "question-circle-fill"),
    "closed": ("neutral", "check2-all"),
    # lots ML
    "running": ("info", "arrow-repeat"), "succeeded": ("success", "check-circle-fill"), "partial": ("warning", "exclamation-triangle-fill"),
    "unavailable": ("warning", "plug-fill"),
    # alertes ML : détectée -> vérification -> décision humaine
    "unreviewed": ("warning", "exclamation-triangle-fill"), "needs_info": ("info", "hourglass-split"),
    "confirmed": ("neutral", "person-check-fill"), "dismissed": ("neutral", "person-check"),
    # recommandations réglementaires
    "reco_congratulate": ("success", "award-fill"), "reco_warning": ("warning", "exclamation-triangle-fill"),
    "reco_sanction_review": ("danger", "hammer"), "reco_compliant": ("info", "check2-circle"),
    "reco_insufficient": ("neutral", "hourglass-split"),
    # opérateurs
    "active": ("success", "check-circle-fill"), "inactive": ("neutral", "pause-circle"),
}


@register.simple_tag
def criteria_map():
    """{code: {label, category, category_label, position}} dans l'ordre configuré par le backend."""
    return {c.code: {"label": c.label, "category": c.category, "category_label": _CATEGORY_LABELS.get(c.category, c.category), "position": c.position}
            for c in Criterion.objects.all()}


@register.simple_tag
def operators_map():
    """{code: {name, index}} ; l'index fixe la couleur de série pour que chaque opérateur garde la même couleur partout."""
    return {o.code: {"name": o.name, "index": i, "active": o.is_active} for i, o in enumerate(Operator.objects.order_by("code"))}


@register.simple_tag
def import_columns():
    """Colonnes reconnues par l'import (schéma feedback_import_v1), pour l'aperçu côté client."""
    return ["external_id", "operator_code", "collected_at", "comment"] + [f"score_{c.code}" for c in Criterion.objects.filter(is_active=True)]


@register.simple_tag(takes_context=True)
def active_nav(context, *prefixes):
    """'active' si le nom de la vue courante commence par l'un des préfixes."""
    match = getattr(context.get("request"), "resolver_match", None)
    name = match.view_name if match else ""
    return "active" if any(name == p or name.startswith(p) for p in prefixes) else ""


@register.simple_tag
def status_badge(status, label=""):
    variant, icon = BADGES.get(status, ("neutral", "dot"))
    return format_html('<span class="ar-badge is-{}"><i class="bi bi-{}" aria-hidden="true"></i>{}</span>', variant, icon, label or status)


@register.filter
def get_item(mapping, key):
    try:
        return mapping.get(key)
    except AttributeError:
        return None


@register.filter
def pct(rate):
    """0.5234 -> 52 (entier, pour « 52 % »)."""
    try:
        return round(float(rate) * 100)
    except (TypeError, ValueError):
        return 0


@register.filter
def reason_label(code):
    return ERROR_MESSAGES.get(code) or EXTRA_REASON_LABELS.get(code) or code


@register.filter
def initials(name):
    return "".join(w[0] for w in str(name).split()[:2]).upper() or "?"


@register.filter
def bs(field):
    """Rend un champ Django avec les classes Bootstrap et les attributs ARIA (erreur, aide)."""
    widget = field.field.widget
    kind = widget.__class__.__name__
    attrs = dict(widget.attrs)
    if kind == "CheckboxInput":
        css = "form-check-input"
    elif "Select" in kind and "Multiple" not in kind:
        css = "form-select"
    else:
        css = "form-control"
    attrs["class"] = f"{attrs.get('class', '')} {css}{' is-invalid' if field.errors else ''}".strip()
    described = []
    if field.help_text:
        described.append(f"{field.auto_id}_help")
    if field.errors:
        described.append(f"{field.auto_id}_err")
        attrs["aria-invalid"] = "true"
    if described:
        attrs["aria-describedby"] = " ".join(described)
    return field.as_widget(attrs=attrs)


@register.filter
def sum_by(items, key):
    """Somme d'un champ numérique sur une liste de dictionnaires."""
    return sum((i.get(key) or 0) for i in items or [])


@register.filter
def merge_sources(indicators):
    """Additionne les volumes par source de plusieurs indicateurs : {source: n}."""
    total = {}
    for ind in indicators or []:
        for source, n in (ind.get("sources") or {}).items():
            total[source] = total.get(source, 0) + n
    return total


@register.filter
def open_complaints(by_status):
    """Réclamations à traiter : reçues + en cours d'examen + informations demandées."""
    return sum((by_status or {}).get(k, 0) for k in ("received", "under_review", "info_requested"))
