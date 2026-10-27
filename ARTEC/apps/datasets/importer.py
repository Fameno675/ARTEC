"""Import CSV / Excel (.xlsx) : schéma `feedback_import_v1`.

Principes :
- erreur structurelle (taille, format, colonnes) -> le fichier entier échoue, rien n'est écrit dans les avis ;
- erreurs par ligne -> lignes classées accepted / rejected / to_review ;
- les avis sont écrits dans UNE transaction ; si plus de IMPORT_MAX_REJECT_RATE des lignes sont rejetées,
  tout le lot est refusé ;
- aucune formule, macro ou code du fichier n'est exécuté : lecture de valeurs uniquement (pandas + openpyxl).
"""
import csv
import io
import os
import re
import uuid
import zipfile
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

import pandas as pd
from django.conf import settings
from django.core.files.base import ContentFile
from django.db import transaction
from django.utils import timezone

from apps.audit.services import log
from apps.common.classification import review_reasons
from apps.common.utils import clean_text, neutralize_cell, sha256_bytes
from apps.feedback.hashing import content_hash, external_key_hash
from apps.feedback.models import Criterion, FeedbackRating, FeedbackSubmission, Source, ValidationStatus
from apps.operators.models import Operator

from .models import DataSourceType, ImportBatch, ImportRowResult, ImportStatus, RowStatus

SCHEMA_VERSION = "feedback_import_v1"
MAX_YEARS_BACK = 5
MAX_UNCOMPRESSED_XLSX = 200 * 1024 * 1024

ERROR_MESSAGES = {
    "date_missing": "Date de collecte manquante.",
    "date_invalid": "Date invalide (format attendu AAAA-MM-JJ).",
    "date_in_future": "Date dans le futur.",
    "date_too_old": "Date antérieure à 5 ans.",
    "score_invalid": "Note non numérique.",
    "score_not_integer": "Note non entière (les décimaux sont refusés).",
    "score_out_of_range": "Note hors de l'échelle 0-10.",
    "no_scores": "Aucune note renseignée.",
    "operator_missing": "Code opérateur manquant.",
    "operator_unknown": "Code opérateur inconnu ou inactif.",
    "operator_not_allowed": "Opérateur non autorisé pour ce compte.",
    "comment_too_long": "Commentaire de plus de 500 caractères.",
    "external_id_too_long": "Identifiant externe de plus de 100 caractères.",
    "duplicate_in_file": "Doublon d'une ligne précédente du fichier.",
    "duplicate_in_db": "Avis déjà enregistré.",
    "all_scores_identical_extreme": "Toutes les notes identiques (0 ou 10) : à examiner.",
    "date_older_than_2_years": "Date de plus de 2 ans : à examiner.",
    "comment_contains_url": "Le commentaire contient une URL : à examiner.",
    "external_id_conflict": "Identifiant externe déjà vu avec des notes différentes : à examiner.",
}
DUPLICATE_CODES = {"duplicate_in_file", "duplicate_in_db"}


class ImportStructureError(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass
class RowOutcome:
    row_number: int
    status: str
    error_codes: list = field(default_factory=list)
    raw: dict = field(default_factory=dict)
    parsed: dict | None = None


# ---------------------------------------------------------------- lecture -----
def _detect_format(filename: str):
    ext = os.path.splitext(filename or "")[1].lower()
    if ext == ".csv":
        return "csv"
    if ext == ".xlsx":
        return "xlsx"
    raise ImportStructureError("unsupported_format", "Format refusé : seuls .csv et .xlsx sont acceptés.")


def _read_csv(content: bytes) -> pd.DataFrame:
    if b"\x00" in content[:4096]:
        raise ImportStructureError("not_text", "Le fichier CSV contient des octets binaires.")
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise ImportStructureError("encoding_error", "Le CSV doit être encodé en UTF-8.")
    first = text.split("\n", 1)[0]
    sep = ";" if first.count(";") > first.count(",") else ","
    try:
        return pd.read_csv(io.StringIO(text), sep=sep, dtype=str, keep_default_na=False, na_filter=False,
                           on_bad_lines="error", skip_blank_lines=True)
    except (pd.errors.ParserError, pd.errors.EmptyDataError) as exc:
        raise ImportStructureError("csv_parse_error", f"CSV illisible : {exc}")


def _read_xlsx(content: bytes) -> pd.DataFrame:
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as zf:
            names = set(zf.namelist())
            if "xl/workbook.xml" not in names or "[Content_Types].xml" not in names:
                raise ImportStructureError("invalid_xlsx", "Fichier .xlsx invalide.")
            if "xl/vbaProject.bin" in names:
                raise ImportStructureError("macro_refused", "Les classeurs avec macros sont refusés.")
            if sum(i.file_size for i in zf.infolist()) > MAX_UNCOMPRESSED_XLSX:
                raise ImportStructureError("xlsx_too_large", "Classeur trop volumineux une fois décompressé.")
    except zipfile.BadZipFile:
        raise ImportStructureError("invalid_xlsx", "Fichier .xlsx invalide.")
    try:
        xl = pd.ExcelFile(io.BytesIO(content), engine="openpyxl")
        sheet = "feedback" if "feedback" in xl.sheet_names else xl.sheet_names[0]
        df = xl.parse(sheet, dtype=str, keep_default_na=False, na_filter=False)
    except ImportStructureError:
        raise
    except Exception as exc:  # openpyxl lève des erreurs variées sur fichiers corrompus
        raise ImportStructureError("xlsx_parse_error", f"Excel illisible : {type(exc).__name__}")
    return df.fillna("")


def _normalise_columns(df, criteria_codes, require_operator):
    mapping, warnings, seen = {}, [], set()
    for col in df.columns:
        key = clean_text(col).lower()
        if key in seen:
            warnings.append(f"Colonne dupliquée ignorée : {col}")
            continue
        seen.add(key)
        known = key in ("external_id", "operator_code", "collected_at", "comment") or (
            key.startswith("score_") and key[6:] in criteria_codes
        )
        if known:
            mapping[col] = key
        else:
            warnings.append(f"Colonne inconnue ignorée : {col}")
    df = df[list(mapping.keys())].rename(columns=mapping)
    missing = [c for c in ("collected_at",) + (("operator_code",) if require_operator else ()) if c not in df.columns]
    if missing:
        raise ImportStructureError("missing_columns", "Colonnes obligatoires absentes : " + ", ".join(missing))
    if not any(c.startswith("score_") for c in df.columns):
        raise ImportStructureError("no_score_columns", "Aucune colonne score_* reconnue.")
    return df, warnings


# --------------------------------------------------------------- validation ---
_INT = re.compile(r"\d+(\.0+)?")


def parse_score(raw: str):
    """Retourne (valeur|None, code_erreur|None). Vide -> (None, None)."""
    s = clean_text(raw).replace(",", ".") if isinstance(raw, str) else clean_text(raw)
    if s == "":
        return None, None
    if _INT.fullmatch(s):
        v = int(float(s))
        return (v, None) if 0 <= v <= 10 else (None, "score_out_of_range")
    try:
        f = float(s)
    except ValueError:
        return None, "score_invalid"
    if f != f or f in (float("inf"), float("-inf")):
        return None, "score_invalid"
    return None, ("score_out_of_range" if f == int(f) else "score_not_integer")


def parse_date(raw: str, today: date):
    s = clean_text(raw)
    if not s:
        return None, "date_missing"
    if len(s) > 10 and s[10] in " T" and re.fullmatch(r"[0-9:.\s+Z-]*", s[11:] or ""):
        s = s[:10]  # Excel renvoie "2026-03-01 00:00:00"
    try:
        d = datetime.strptime(s, "%Y-%m-%d").date()
    except ValueError:
        return None, "date_invalid"
    if d > today:
        return None, "date_in_future"
    if d < today - timedelta(days=365 * MAX_YEARS_BACK):
        return None, "date_too_old"
    return d, None


def _classify_rows(df, *, operators_by_code, criteria_by_code, operator_scope, source, today):
    outcomes = []
    for idx, rec in enumerate(df.to_dict("records")):
        row_number = idx + 2  # ligne 1 = en-têtes
        codes = []
        raw = {k: clean_text(v)[:200] for k, v in rec.items()}
        d, err = parse_date(rec.get("collected_at", ""), today)
        if err:
            codes.append(err)
        # opérateur
        code_in = clean_text(rec.get("operator_code", "")).lower()
        operator = None
        if operator_scope is not None:
            if code_in and code_in != operator_scope.code:
                codes.append("operator_not_allowed")
            else:
                operator = operator_scope
        else:
            if not code_in:
                codes.append("operator_missing")
            elif code_in not in operators_by_code:
                codes.append("operator_unknown")
            else:
                operator = operators_by_code[code_in]
        # notes
        scores = {}
        for col in df.columns:
            if col.startswith("score_"):
                val, serr = parse_score(rec.get(col, ""))
                if serr:
                    codes.append(serr)
                elif val is not None:
                    scores[col[6:]] = val
        if not scores and not any(c.startswith("score_") for c in codes):
            codes.append("no_scores")
        comment = clean_text(rec.get("comment", ""))
        if len(comment) > 500:
            codes.append("comment_too_long")
        ext = clean_text(rec.get("external_id", ""))
        if len(ext) > 100:
            codes.append("external_id_too_long")
        codes = list(dict.fromkeys(codes))
        if codes:
            outcomes.append(RowOutcome(row_number, RowStatus.REJECTED, codes, raw))
            continue
        chash = content_hash(operator.code, d, scores, source)
        key = external_key_hash(operator.code, source, ext) if ext else chash
        reasons = review_reasons(scores, comment, d, today=today)
        outcomes.append(RowOutcome(
            row_number, RowStatus.TO_REVIEW if reasons else RowStatus.ACCEPTED, reasons, raw,
            {"operator": operator, "collected_at": d, "scores": scores, "comment": comment,
             "external_id": ext, "dedup_hash": key, "content_hash": chash},
        ))
    return outcomes


def _apply_duplicates(outcomes):
    """Détection des doublons dans le fichier puis en base (sans écrire quoi que ce soit)."""
    first_seen = {}
    for o in outcomes:
        if o.parsed is None:
            continue
        key, chash = o.parsed["dedup_hash"], o.parsed["content_hash"]
        prev = first_seen.get(key)
        if prev is not None:
            if prev == chash:
                o.status, o.error_codes, o.parsed = RowStatus.REJECTED, ["duplicate_in_file"], None
            else:
                o.status, o.error_codes = RowStatus.TO_REVIEW, o.error_codes + ["external_id_conflict"]
        else:
            first_seen[key] = chash
    keys = list({o.parsed["dedup_hash"] for o in outcomes if o.parsed})
    db_seen = {}
    for i in range(0, len(keys), 5000):
        for k, c in FeedbackSubmission.objects.filter(dedup_hash__in=keys[i:i + 5000]).exclude(
            validation_status=ValidationStatus.REJECTED
        ).values_list("dedup_hash", "content_hash"):
            db_seen.setdefault(k, set()).add(c)
    for o in outcomes:
        if o.parsed is None:
            continue
        k, c = o.parsed["dedup_hash"], o.parsed["content_hash"]
        if k in db_seen:
            if c in db_seen[k]:
                o.status, o.error_codes, o.parsed = RowStatus.REJECTED, ["duplicate_in_db"], None
            elif "external_id_conflict" not in o.error_codes:
                o.status, o.error_codes = RowStatus.TO_REVIEW, o.error_codes + ["external_id_conflict"]
    return outcomes


# ---------------------------------------------------------------- orchestration ----
SOURCE_BY_TYPE = {
    DataSourceType.OPERATOR_FILE: Source.OPERATOR_IMPORT,
    DataSourceType.ARTEC_FILE: Source.ARTEC_IMPORT,
}


def source_for(data_source) -> str:
    return SOURCE_BY_TYPE.get(data_source.source_type, Source.EXTERNAL_IMPORT)


def _fail(batch, code, message, **extra):
    batch.status = ImportStatus.FAILED
    batch.error_summary = {"error": code, "message": message, **extra}
    batch.finished_at = timezone.now()
    batch.save()
    log(batch.uploaded_by, "import.failed", batch, error=code, filename=batch.original_filename)
    return batch


def process_import(*, uploaded_file, user, data_source, operator_scope=None, today=None) -> ImportBatch:
    """Point d'entrée unique. Retourne toujours un ImportBatch (committed ou failed)."""
    today = today or timezone.localdate()
    safe_name = clean_text(os.path.basename(getattr(uploaded_file, "name", "") or "fichier"))[:255] or "fichier"
    batch = ImportBatch(
        id=uuid.uuid4(), data_source=data_source, uploaded_by=user, operator=operator_scope,
        original_filename=safe_name, file_size=getattr(uploaded_file, "size", 0) or 0, schema_version=SCHEMA_VERSION,
    )
    try:
        fmt = _detect_format(safe_name)
        batch.file_format = fmt
        if batch.file_size > settings.IMPORT_MAX_FILE_BYTES:
            raise ImportStructureError("file_too_large", f"Fichier trop volumineux (max {settings.IMPORT_MAX_FILE_BYTES // (1024 * 1024)} Mo).")
        content = uploaded_file.read(settings.IMPORT_MAX_FILE_BYTES + 1)
        if len(content) > settings.IMPORT_MAX_FILE_BYTES:
            raise ImportStructureError("file_too_large", "Fichier trop volumineux.")
        batch.file_size = len(content)
        batch.file_sha256 = sha256_bytes(content)
        batch.stored_file.save(f"{batch.id}.{fmt}", ContentFile(content), save=False)
        df = _read_csv(content) if fmt == "csv" else _read_xlsx(content)
        if len(df) == 0:
            raise ImportStructureError("empty_file", "Le fichier ne contient aucune ligne de données.")
        if len(df) > settings.IMPORT_MAX_ROWS:
            raise ImportStructureError("too_many_rows", f"Trop de lignes (max {settings.IMPORT_MAX_ROWS}).")
        criteria_by_code = {c.code: c for c in Criterion.objects.filter(is_active=True)}
        df, warnings = _normalise_columns(df, set(criteria_by_code), require_operator=operator_scope is None)
    except ImportStructureError as exc:
        return _fail(batch, exc.code, exc.message)

    warnings = list(warnings)
    if batch.file_sha256 and ImportBatch.objects.filter(
        file_sha256=batch.file_sha256, operator=operator_scope, status=ImportStatus.COMMITTED
    ).exists():
        warnings.append("Un fichier identique a déjà été importé pour ce périmètre.")

    source = source_for(data_source)
    outcomes = _apply_duplicates(_classify_rows(
        df, operators_by_code={o.code: o for o in Operator.objects.active()}, criteria_by_code=criteria_by_code,
        operator_scope=operator_scope, source=source, today=today,
    ))
    batch.total_rows = len(outcomes)
    batch.accepted_rows = sum(o.status == RowStatus.ACCEPTED for o in outcomes)
    batch.review_rows = sum(o.status == RowStatus.TO_REVIEW for o in outcomes)
    batch.rejected_rows = sum(o.status == RowStatus.REJECTED for o in outcomes)
    batch.duplicate_rows = sum(bool(set(o.error_codes) & DUPLICATE_CODES) for o in outcomes)
    code_counts = {}
    for o in outcomes:
        for c in o.error_codes:
            code_counts[c] = code_counts.get(c, 0) + 1
    summary = {"warnings": warnings, "error_codes": code_counts, "reject_threshold": settings.IMPORT_MAX_REJECT_RATE}

    if batch.rejection_rate > settings.IMPORT_MAX_REJECT_RATE:
        batch.error_summary = {"error": "reject_rate_exceeded", "message": "Trop de lignes rejetées : aucun avis n'a été enregistré.",
                               "rejection_rate": round(batch.rejection_rate, 4), **summary}
        batch.status = ImportStatus.FAILED
        batch.finished_at = timezone.now()
        with transaction.atomic():
            batch.save()
            _save_rows(batch, outcomes, {})
        log(user, "import.failed", batch, error="reject_rate_exceeded", filename=safe_name)
        return batch

    batch.status = ImportStatus.VALIDATED
    try:
        with transaction.atomic():
            batch.save()
            sub_by_row = _save_submissions(batch, outcomes, data_source, source, criteria_by_code)
            _save_rows(batch, outcomes, sub_by_row)
            batch.status = ImportStatus.COMMITTED
            batch.error_summary = summary
            batch.finished_at = timezone.now()
            batch.save()
    except Exception as exc:  # tout est annulé par la transaction
        batch.status = ImportStatus.FAILED
        batch.error_summary = {"error": "commit_failed", "message": f"Échec technique ({type(exc).__name__}) : rien n'a été enregistré.", **summary}
        batch.finished_at = timezone.now()
        ImportBatch.objects.update_or_create(id=batch.id, defaults={
            k: getattr(batch, k) for k in ("data_source_id", "uploaded_by_id", "operator_id", "original_filename", "stored_file",
                                           "file_sha256", "file_size", "file_format", "schema_version", "status", "total_rows",
                                           "accepted_rows", "rejected_rows", "review_rows", "duplicate_rows", "error_summary",
                                           "finished_at")})
        log(user, "import.failed", batch, error="commit_failed", filename=safe_name)
        return batch
    log(user, "import.committed", batch, filename=safe_name, total=batch.total_rows, accepted=batch.accepted_rows,
        rejected=batch.rejected_rows, review=batch.review_rows)
    return batch


def _save_submissions(batch, outcomes, data_source, source, criteria_by_code):
    subs, ratings, row_to_sub = [], [], {}
    for o in outcomes:
        if o.parsed is None or o.status == RowStatus.REJECTED:
            continue
        p = o.parsed
        sub = FeedbackSubmission(
            operator=p["operator"], collected_at=p["collected_at"], source=source, data_source=data_source,
            import_batch=batch, external_id=p["external_id"], dedup_hash=p["dedup_hash"], content_hash=p["content_hash"],
            validation_status=ValidationStatus.ACCEPTED if o.status == RowStatus.ACCEPTED else ValidationStatus.TO_REVIEW,
            validation_reasons=o.error_codes, comment=p["comment"],
        )
        subs.append(sub)
        row_to_sub[o.row_number] = sub
        for code, val in p["scores"].items():
            ratings.append(FeedbackRating(submission=sub, criterion=criteria_by_code[code], score=val))
    FeedbackSubmission.objects.bulk_create(subs, batch_size=2000)
    FeedbackRating.objects.bulk_create(ratings, batch_size=5000)
    return row_to_sub


def _save_rows(batch, outcomes, sub_by_row):
    ImportRowResult.objects.bulk_create(
        [ImportRowResult(batch=batch, row_number=o.row_number, status=o.status, error_codes=o.error_codes,
                         raw_data=o.raw, submission=sub_by_row.get(o.row_number)) for o in outcomes],
        batch_size=5000,
    )


# ------------------------------------------------------------ rapport & modèle ----
def error_report_rows(batch):
    yield ["row_number", "status", "external_id", "error_codes", "messages", "raw_data"]
    for r in batch.rows.exclude(status=RowStatus.ACCEPTED).iterator():
        msgs = " | ".join(ERROR_MESSAGES.get(c, c) for c in r.error_codes)
        raw = "; ".join(f"{k}={v}" for k, v in r.raw_data.items())
        yield [r.row_number, r.status, r.raw_data.get("external_id", ""), ",".join(r.error_codes), msgs, raw]


def error_report_csv(batch) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    for row in error_report_rows(batch):
        w.writerow([neutralize_cell(c) for c in row])
    return buf.getvalue()


def template_csv(for_operator: bool) -> str:
    codes = [c.code for c in Criterion.objects.filter(is_active=True)]
    header = ["external_id", "operator_code", "collected_at"] + [f"score_{c}" for c in codes] + ["comment"]
    example = ["EXEMPLE-001", "" if for_operator else "orange", timezone.localdate().isoformat()] + \
        [str(5 + (i % 4)) for i in range(len(codes))] + ["Exemple (à supprimer)"]
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(header)
    w.writerow(example)
    return buf.getvalue()
