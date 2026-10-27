"""Étape 1 (a) : normalisation et conversion de types.

Principes :
- aucune ligne n'est supprimée ici (la validation les statue) ;
- les valeurs manquantes restent NaN (aucune imputation, aucune fausse observation) ;
- données personnelles minimisées : l'identifiant visiteur est remplacé par un
  condensat salé, le texte des commentaires par sa longueur et son condensat ;
- chaque transformation est consignée dans un journal.
"""
from __future__ import annotations

import hashlib
import re
import unicodedata
from pathlib import Path
from typing import List, Tuple

import numpy as np
import pandas as pd

from .schemas import (COLUMN_ALIASES, CRITERIA_KEYS, OPERATOR_ALIASES, REQUIRED_COLUMNS,
                      EngineConfig)


class SchemaError(ValueError):
    """Le lot ne respecte pas le schéma minimal : analyse impossible."""


def norm_name(value) -> str:
    s = unicodedata.normalize("NFKD", str(value)).encode("ascii", "ignore").decode()
    return re.sub(r"[^0-9a-z]+", "_", s.strip().lower()).strip("_")


def load_input(data) -> pd.DataFrame:
    """Accepte DataFrame, liste de dict, chemin CSV/XLSX."""
    if isinstance(data, pd.DataFrame):
        df = data.copy()
    elif isinstance(data, (str, Path)):
        p = Path(data)
        if not p.exists():
            raise FileNotFoundError(f"Fichier introuvable : {p}")
        ext = p.suffix.lower()
        if ext in (".xlsx", ".xlsm"):
            df = pd.read_excel(p, engine="openpyxl")
        elif ext in (".csv", ".txt"):
            df = pd.read_csv(p, sep=None, engine="python", dtype=str, encoding="utf-8-sig")
        else:
            raise ValueError(f"Format non supporté : {ext}")
    elif isinstance(data, (list, tuple)):
        df = pd.DataFrame(list(data))
    else:
        raise TypeError("data doit être un DataFrame, une liste de dict ou un chemin CSV/XLSX")
    if df.empty:
        raise SchemaError("Le lot est vide.")
    return df.reset_index(drop=True)


def _to_numeric(s: pd.Series) -> Tuple[pd.Series, pd.Series]:
    """Retourne (valeurs float, masque 'non numérique mais renseigné')."""
    if pd.api.types.is_numeric_dtype(s) and not pd.api.types.is_bool_dtype(s):
        return s.astype(float), pd.Series(False, index=s.index)
    txt = s.astype(object).map(
        lambda v: None if pd.isna(v) or str(v).strip() == "" else str(v).strip().replace(",", ".")
    )
    num = pd.to_numeric(txt, errors="coerce").astype(float)
    bad = txt.notna() & num.isna()
    return num, bad


def _hash(value, salt: str):
    if value is None or pd.isna(value) or str(value).strip() == "":
        return np.nan
    return hashlib.sha256((salt + str(value).strip()).encode("utf-8")).hexdigest()[:16]


_LABEL_MAP = {"1": 1, "unreliable": 1, "non_fiable": 1, "peu_fiable": 1,
              "0": 0, "reliable": 0, "fiable": 0}


def preprocess(raw: pd.DataFrame, config: EngineConfig) -> Tuple[pd.DataFrame, List[dict]]:
    log: List[dict] = []

    def note(step, detail, count=None):
        log.append({"step": step, "detail": detail, "count": count})

    # 1. normalisation des noms de colonnes
    mapping, ignored, seen = {}, [], set()
    for col in raw.columns:
        canon = COLUMN_ALIASES.get(norm_name(col))
        if canon is None or canon in seen:
            ignored.append(str(col))
            continue
        mapping[col] = canon
        seen.add(canon)
    df = raw[list(mapping)].rename(columns=mapping).copy()
    note("normalize_columns", f"{len(mapping)} colonnes reconnues", len(mapping))
    if ignored:
        note("ignored_columns", "Colonnes non reconnues ou en doublon, ignorées : " + ", ".join(ignored), len(ignored))

    # 2. schéma minimal
    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if not any(k in df.columns for k in CRITERIA_KEYS):
        missing.append("au moins une colonne de critère (notes 0-10)")
    if missing:
        raise SchemaError("Colonnes obligatoires manquantes : " + ", ".join(missing))

    df.insert(0, "row_number", np.arange(1, len(df) + 1))

    # 3. identifiants et chaînes
    if "obs_id" not in df.columns:
        df["obs_id"] = np.nan
    gen = df["obs_id"].isna() | (df["obs_id"].astype(str).str.strip() == "")
    df["obs_id"] = df["obs_id"].astype(object)
    df.loc[gen, "obs_id"] = ["row-%d" % n for n in df.loc[gen, "row_number"]]
    if gen.any():
        note("generated_obs_id", "Identifiants générés pour les lignes sans id", int(gen.sum()))
    df["obs_id"] = df["obs_id"].astype(str)

    # 4. opérateur
    op_raw = df["operator"].astype(object).map(lambda v: None if pd.isna(v) else str(v).strip())
    df["operator_raw"] = op_raw
    df["operator"] = op_raw.map(lambda v: OPERATOR_ALIASES.get(norm_name(v).replace("_", " ")) if v else None)
    note("normalize_operator", "Noms d'opérateurs ramenés aux noms canoniques ; inconnus -> NaN (rejetés ensuite)",
         int(df["operator"].isna().sum()))

    # 5. source
    if "source" not in df.columns:
        df["source"] = np.nan
    src = df["source"].astype(object).map(lambda v: None if pd.isna(v) or str(v).strip() == "" else norm_name(v))
    n_src = int(src.isna().sum())
    df["source"] = src.fillna("unspecified")
    if n_src:
        note("default_source", "Source absente -> 'unspecified' (métadonnée, pas une observation)", n_src)

    # 6. dates (UTC ; les dates naïves sont interprétées comme UTC : envoyer de l'ISO 8601 avec offset)
    try:
        ts = pd.to_datetime(df["submitted_at"], errors="coerce", utc=True,
                            dayfirst=config.date_dayfirst, format="mixed")
    except (ValueError, TypeError):
        ts = pd.to_datetime(df["submitted_at"], errors="coerce", utc=True, dayfirst=config.date_dayfirst)
    df["submitted_at"] = ts
    note("parse_dates", "Dates converties en UTC ; non interprétables -> NaT", int(ts.isna().sum()))

    # 7. notes
    for k in CRITERIA_KEYS:
        if k not in df.columns:
            df[k] = np.nan
    nonnum = [[] for _ in range(len(df))]
    n_bad = 0
    for k in CRITERIA_KEYS:
        num, bad = _to_numeric(df[k])
        df[k] = num
        for i in np.flatnonzero(bad.to_numpy()):
            nonnum[i].append(k)
            n_bad += 1
    df["nonnumeric_fields"] = nonnum
    absent = [k for k in CRITERIA_KEYS if k not in raw.columns and k not in mapping.values()]
    if absent:
        note("absent_criteria", "Critères absents du lot (laissés vides, non imputés) : " + ", ".join(absent), len(absent))
    note("numeric_conversion", "Notes converties en nombres (virgule décimale acceptée) ; valeurs non numériques -> NaN", n_bad)

    # 8. minimisation des données personnelles
    salt = config.visitor_salt
    df["visitor_key"] = df["visitor_id"].map(lambda v: _hash(v, salt)) if "visitor_id" in df.columns else np.nan
    if "visitor_id" in df.columns:
        df = df.drop(columns=["visitor_id"])
        note("pseudonymize_visitor", "Identifiant visiteur remplacé par un condensat salé (non réversible)", None)
    if "comment" in df.columns:
        cm = df["comment"].astype(object).map(lambda v: "" if pd.isna(v) else " ".join(str(v).lower().split()))
        df["comment_len"] = cm.str.len().astype(int)
        df["comment_hash"] = cm.map(lambda v: _hash(v, "c") if v else np.nan)
        df = df.drop(columns=["comment"])
        note("drop_comment_text", "Texte des commentaires non conservé : seuls longueur et condensat servent aux contrôles", None)
    else:
        df["comment_len"] = 0
        df["comment_hash"] = np.nan
    if "batch_ref" not in df.columns:
        df["batch_ref"] = np.nan

    # 9. labels vérifiés éventuels (1 = non fiable, 0 = fiable)
    if "verified_label" in df.columns:
        df["label_unreliable"] = df["verified_label"].map(
            lambda v: _LABEL_MAP.get(norm_name(v)) if not pd.isna(v) else np.nan).astype(float)
        df = df.drop(columns=["verified_label"])
        note("labels", "Labels vérifiés détectés", int(df["label_unreliable"].notna().sum()))

    keep = ["row_number", "obs_id", "operator_raw", "operator", "source", "submitted_at",
            "visitor_key", "batch_ref", "comment_len", "comment_hash"] + CRITERIA_KEYS + ["nonnumeric_fields"]
    if "label_unreliable" in df.columns:
        keep.append("label_unreliable")
    return df[keep], log
