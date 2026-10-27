"""Étapes 2 et 5 : indicateurs descriptifs, scores de qualité PERÇUE, comparaison des opérateurs.

Règles de calcul (reproductibles, sans aléa) :
- note basse : < low_threshold ; haute : >= high_threshold ; moyenne : entre les deux ;
- score d'un critère = moyenne des notes valides ;
- score d'une dimension (internet, appels, ...) : par observation, moyenne PONDÉRÉE des critères
  renseignés de la dimension (poids = config.criterion_weights, 1.0 par défaut) ; puis moyenne
  sur les observations. L'IC 95 % est calculé sur ces scores par observation (loi t de Student) ;
- score global (facultatif, config.compute_global) : moyenne pondérée des dimensions renseignées
  (config.global_weights, 1.0 par défaut). Les dimensions n'ayant pas la même nature, il n'est jamais
  mélangé aux scores de dimension et reste désactivé par défaut ;
- un résultat dont n < min_n_reliable est marqué reliable_sample = false.
Ces scores mesurent une PERCEPTION DÉCLARÉE, pas une mesure technique du réseau.
"""
from __future__ import annotations

from itertools import combinations
from typing import Dict, List

import numpy as np
import pandas as pd
from scipy import stats as sps

from .schemas import CRITERIA, CRITERIA_KEYS, DIMENSIONS, EngineConfig

REPRESENTATIVITY_NOTES = [
    "Les avis publics sont auto-sélectionnés (aucun compte requis) : les mécontents et les très satisfaits "
    "sont généralement sur-représentés ; l'échantillon n'est pas probabiliste.",
    "Les résultats ne sont pas extrapolables à la population des abonnés sans pondération/redressement.",
    "Un même visiteur peut soumettre plusieurs avis : les observations ne sont pas strictement indépendantes "
    "(les IC sont donc optimistes).",
    "Les fichiers fournis par les opérateurs et les sondages ont des biais de collecte différents ; "
    "comparer sources et périodes avec prudence.",
    "Une note faible n'indique ni une fraude ni une violation : c'est une perception déclarée.",
]


def _r(x, nd=3):
    return None if x is None or (isinstance(x, float) and np.isnan(x)) else round(float(x), nd)


def _stats(s: pd.Series, config: EngineConfig) -> dict:
    s = s.dropna().astype(float)
    n = int(len(s))
    if n == 0:
        return {"n": 0, "mean": None, "median": None, "std": None, "ci95_low": None, "ci95_high": None,
                "share_low": None, "share_mid": None, "share_high": None, "reliable_sample": False}
    mean = float(s.mean())
    sd = float(s.std(ddof=1)) if n > 1 else None
    lo = hi = None
    if n > 1:
        half = sps.t.ppf(0.975, n - 1) * sd / np.sqrt(n)
        lo, hi = max(config.rating_min, mean - half), min(config.rating_max, mean + half)
    low = float((s < config.low_threshold).mean())
    high = float((s >= config.high_threshold).mean())
    return {"n": n, "mean": _r(mean), "median": _r(s.median()), "std": _r(sd), "ci95_low": _r(lo), "ci95_high": _r(hi),
            "share_low": _r(low), "share_mid": _r(1 - low - high), "share_high": _r(high),
            "reliable_sample": n >= config.min_n_reliable}


def dimension_scores(df: pd.DataFrame, config: EngineConfig) -> pd.DataFrame:
    """Score par observation et par dimension (colonnes 'dim_<nom>')."""
    out = {}
    for dim, crits in DIMENSIONS.items():
        w = np.array([config.criterion_weights.get(c, 1.0) for c in crits], dtype=float)
        vals = df[crits].to_numpy(dtype=float)
        mask = ~np.isnan(vals)
        num = np.where(mask, vals, 0.0) @ w
        den = mask @ w
        with np.errstate(invalid="ignore", divide="ignore"):
            out[f"dim_{dim}"] = np.where(den > 0, num / den, np.nan)
    return pd.DataFrame(out, index=df.index)


def global_scores(dims: pd.DataFrame, config: EngineConfig) -> pd.Series:
    cols = list(dims.columns)
    w = np.array([config.global_weights.get(c[4:], 1.0) for c in cols], dtype=float)
    vals = dims.to_numpy(dtype=float)
    mask = ~np.isnan(vals)
    num = np.where(mask, vals, 0.0) @ w
    den = mask @ w
    with np.errstate(invalid="ignore", divide="ignore"):
        return pd.Series(np.where(den > 0, num / den, np.nan), index=dims.index)


def compute_quality(df: pd.DataFrame, config: EngineConfig) -> dict:
    warnings: List[dict] = []
    dims = dimension_scores(df, config)
    glob = global_scores(dims, config) if config.compute_global else None

    by_op: Dict[str, dict] = {}
    for op, g in df.groupby("operator"):
        entry = {"n_valid": int(len(g)), "criteria": {}, "dimensions": {}, "global_score": None}
        for k in CRITERIA_KEYS:
            entry["criteria"][k] = {"label": CRITERIA[k][0], **_stats(g[k], config)}
        for dim, crits in DIMENSIONS.items():
            entry["dimensions"][dim] = {**_stats(dims.loc[g.index, f"dim_{dim}"], config), "criteria_used": crits,
                                        "weights": {c: config.criterion_weights.get(c, 1.0) for c in crits}}
        if glob is not None:
            entry["global_score"] = {**_stats(glob.loc[g.index], config),
                                     "weights": {d: config.global_weights.get(d, 1.0) for d in DIMENSIONS},
                                     "warning": "Agrège des dimensions de nature différente ; dépend des poids choisis."}
        if len(g) < config.min_n_reliable:
            warnings.append({"code": "small_sample", "operator": op,
                             "message": f"{op} : seulement {len(g)} avis valides (< {config.min_n_reliable}) : "
                                        "scores indicatifs, comparaisons déconseillées."})
        by_op[op] = entry

    # évolution temporelle
    trend: Dict[str, list] = {}
    for op, g in df.groupby("operator"):
        frame = pd.concat([g[["submitted_at"]], dims.loc[g.index]], axis=1)
        rows = []
        for per, sub in frame.groupby(pd.Grouper(key="submitted_at", freq=config.trend_freq)):
            if len(sub) == 0:
                continue
            rows.append({"period_end": per.isoformat(), "n_obs": int(len(sub)),
                         "low_sample": bool(len(sub) < config.min_n_period),
                         "dimensions": {d: _r(sub[f"dim_{d}"].mean()) for d in DIMENSIONS}})
        trend[op] = rows

    # comparaison entre opérateurs (par dimension), avec prudence
    comparisons: Dict[str, dict] = {}
    for dim in DIMENSIONS:
        elig = {op: e["dimensions"][dim] for op, e in by_op.items()
                if e["dimensions"][dim]["n"] >= config.min_n_reliable}
        ranking = sorted(elig.items(), key=lambda kv: kv[1]["mean"], reverse=True)
        pairs = []
        for (a, sa), (b, sb) in combinations(ranking, 2):
            overlap = not (sa["ci95_low"] > sb["ci95_high"] or sb["ci95_low"] > sa["ci95_high"])
            pairs.append({"a": a, "b": b, "difference": _r(sa["mean"] - sb["mean"]),
                          "ci_overlap": overlap,
                          "reading": "différence non démontrée (IC qui se chevauchent)" if overlap
                          else "différence de perception probable ; ne prouve aucune faute"})
        comparisons[dim] = {"ranking": [{"operator": op, "score": s["mean"], "n": s["n"]} for op, s in ranking],
                            "pairs": pairs,
                            "excluded_small_sample": [op for op in by_op if op not in elig]}

    # cohérence des périodes / sources entre opérateurs
    if df["operator"].nunique() > 1:
        span = (df["submitted_at"].max() - df["submitted_at"].min()).total_seconds()
        if span > 0:
            for op, g in df.groupby("operator"):
                cov = (g["submitted_at"].max() - g["submitted_at"].min()).total_seconds() / span
                if cov < 0.8:
                    warnings.append({"code": "period_mismatch", "operator": op,
                                     "message": f"{op} : données couvrant {cov:.0%} de la période du lot ; comparaison à interpréter avec prudence."})
        share = df.assign(pub=df["source"].eq("public_review")).groupby("operator")["pub"].mean()
        if share.max() - share.min() > 0.3:
            warnings.append({"code": "source_mix_mismatch",
                             "message": "La part d'avis publics diffère fortement selon les opérateurs : biais de composition possible."})
    return {"by_operator": by_op, "trend": trend, "comparisons": comparisons, "warnings": warnings,
            "representativity_notes": REPRESENTATIVITY_NOTES}
