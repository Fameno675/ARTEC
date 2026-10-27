"""Étape 1 (b) : validation structurelle + profil des données.

Chaque ligne reçoit un statut : accepted / review / rejected, avec ses motifs.
Aucune ligne n'est supprimée silencieusement.
"""
from __future__ import annotations

from typing import Dict, List, Tuple

import numpy as np
import pandas as pd

from .schemas import CRITERIA_KEYS, EngineConfig

REASON_MESSAGES: Dict[str, str] = {
    "unknown_operator": "Opérateur absent ou non reconnu.",
    "invalid_date": "Date absente ou non interprétable.",
    "date_out_of_range": "Date antérieure à la date minimale valide.",
    "future_date": "Date située dans le futur.",
    "no_ratings": "Aucune note exploitable.",
    "rating_out_of_range": "Au moins une note hors de la plage autorisée.",
    "exact_duplicate": "Doublon exact d'une observation précédente du lot.",
    "probable_duplicate": "Même visiteur, même opérateur et mêmes notes à quelques minutes d'intervalle.",
    "duplicate_obs_id": "Identifiant d'observation déjà utilisé avec un contenu différent.",
    "non_numeric_value": "Valeur(s) non numérique(s) ignorée(s) dans les notes.",
}

_REJECT = {"unknown_operator", "invalid_date", "date_out_of_range", "future_date",
           "no_ratings", "rating_out_of_range", "exact_duplicate"}


def validate(df: pd.DataFrame, config: EngineConfig) -> Tuple[pd.DataFrame, dict]:
    df = df.copy()
    R = df[CRITERIA_KEYS]
    reasons: List[List[str]] = [[] for _ in range(len(df))]

    def add(mask, code):
        for i in np.flatnonzero(np.asarray(mask, dtype=bool)):
            if code not in reasons[i]:
                reasons[i].append(code)

    now = pd.Timestamp(config.reference_now, tz="UTC") if config.reference_now else pd.Timestamp.now(tz="UTC")
    ts = df["submitted_at"]

    add(df["operator"].isna(), "unknown_operator")
    add(ts.isna(), "invalid_date")
    add(ts.notna() & (ts < pd.Timestamp(config.min_valid_date, tz="UTC")), "date_out_of_range")
    add(ts.notna() & (ts > now + pd.Timedelta(hours=config.future_tolerance_hours)), "future_date")
    add(R.notna().sum(axis=1) == 0, "no_ratings")
    add(((R < config.rating_min) | (R > config.rating_max)).any(axis=1), "rating_out_of_range")
    add(df["nonnumeric_fields"].map(len) > 0, "non_numeric_value")

    subset = ["operator", "source", "submitted_at", "visitor_key", "comment_hash"] + CRITERIA_KEYS
    exact = df.duplicated(subset=subset, keep="first").to_numpy()
    add(exact, "exact_duplicate")

    dup_id = df["obs_id"].duplicated(keep="first").to_numpy() & ~exact
    add(dup_id, "duplicate_obs_id")

    # doublons probables : même visiteur + opérateur + notes dans une fenêtre courte
    keys = ["visitor_key", "operator"] + CRITERIA_KEYS
    tmp = df.sort_values("submitted_at")
    gap = tmp.groupby(keys, dropna=False)["submitted_at"].diff()
    probable = (gap.notna() & (gap <= pd.Timedelta(minutes=config.duplicate_window_minutes))
                & tmp["visitor_key"].notna())
    probable = probable.reindex(df.index).fillna(False).to_numpy() & ~exact
    add(probable, "probable_duplicate")

    for rule in config.extra_rules:  # hook : règles de cohérence inter-champs propres à ARTEC
        try:
            codes = rule(df)
            for i, c in enumerate(codes):
                if c and c not in reasons[i]:
                    reasons[i].append(str(c))
        except Exception:  # une règle défaillante ne doit pas bloquer le lot
            pass

    status = []
    for r in reasons:
        if any(c in _REJECT for c in r):
            status.append("rejected")
        elif r:
            status.append("review")
        else:
            status.append("accepted")
    df["validation_status"] = status
    df["validation_reasons"] = reasons

    counts: Dict[str, int] = {}
    for r in reasons:
        for c in r:
            counts[c] = counts.get(c, 0) + 1
    report = {
        "accepted": int((df["validation_status"] == "accepted").sum()),
        "review": int((df["validation_status"] == "review").sum()),
        "rejected": int((df["validation_status"] == "rejected").sum()),
        "reason_counts": counts,
        "reason_messages": {c: REASON_MESSAGES.get(c, c) for c in counts},
    }
    return df, report


def profile_batch(raw: pd.DataFrame, clean: pd.DataFrame, config: EngineConfig) -> dict:
    """Profil descriptif du lot (nombre de lignes, types, manquants, période, labels...)."""
    ts = clean["submitted_at"].dropna()
    dist = {}
    for k in CRITERIA_KEYS:
        v = clean[k].dropna()
        v = v[(v >= config.rating_min) & (v <= config.rating_max)]
        counts = v.round().astype(int).value_counts().reindex(range(int(config.rating_min), int(config.rating_max) + 1), fill_value=0)
        dist[k] = {"n": int(len(v)), "missing": int(clean[k].isna().sum()),
                   "histogram": {str(i): int(c) for i, c in counts.items()}}
    labels = clean["label_unreliable"].dropna() if "label_unreliable" in clean else pd.Series(dtype=float)
    return {
        "n_rows": int(len(raw)),
        "n_columns": int(raw.shape[1]),
        "columns": {str(c): {"dtype": str(raw[c].dtype), "missing": int(raw[c].isna().sum())} for c in raw.columns},
        "period": {"min": ts.min().isoformat() if len(ts) else None, "max": ts.max().isoformat() if len(ts) else None},
        "by_source": clean["source"].value_counts().to_dict(),
        "by_operator": clean["operator"].fillna("(inconnu)").value_counts().to_dict(),
        "rating_distributions": dist,
        "verified_labels": {"present": bool(len(labels)), "n_labeled": int(len(labels)),
                            "n_reliable": int((labels == 0).sum()), "n_unreliable": int((labels == 1).sum())},
    }
