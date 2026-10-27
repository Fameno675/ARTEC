"""Construction des variables utilisées par les règles et les modèles.

Ne dépend que de signaux comportementaux (notes, horaires, volumes, répétitions).
Aucune tentative d'identification d'une personne.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .schemas import CRITERIA_KEYS, EngineConfig

FEATURE_COLUMNS = [
    "n_ratings", "mean_rating", "std_rating", "rating_range", "share_extreme", "all_equal",
    "dev_from_operator_median", "hour_sin", "hour_cos", "comment_len_log",
    "visitor_batch_count", "visitor_burst_count", "op_hour_volume", "comment_repeat_count",
]
_EPOCH = pd.Timestamp("1970-01-01", tz="UTC")


def window_counts(ts: pd.Series, groups: pd.Series, window_seconds: float) -> pd.Series:
    """Pour chaque ligne : nb de lignes du même groupe dans les `window` secondes précédentes (elle incluse)."""
    out = pd.Series(1.0, index=ts.index)
    secs = (ts - _EPOCH).dt.total_seconds()
    frame = pd.DataFrame({"g": groups, "s": secs}).dropna()
    for _, sub in frame.groupby("g"):
        sub = sub.sort_values("s")
        s = sub["s"].to_numpy()
        cnt = np.arange(1, len(s) + 1) - np.searchsorted(s, s - window_seconds, side="left")
        out.loc[sub.index] = cnt
    return out


def build_features(df: pd.DataFrame, config: EngineConfig) -> pd.DataFrame:
    R = df[CRITERIA_KEYS]
    n = R.notna().sum(axis=1).astype(float)
    mean = R.mean(axis=1)
    rng = (R.max(axis=1) - R.min(axis=1)).fillna(0.0)
    extreme = ((R <= config.rating_min) | (R >= config.rating_max)).sum(axis=1) / n.replace(0, np.nan)

    local = df["submitted_at"].dt.tz_convert(config.timezone)
    hour = local.dt.hour + local.dt.minute / 60.0

    gkey = (df["visitor_key"].astype(object) + "|" + df["operator"].astype(object))
    vc = gkey.map(gkey.value_counts()).fillna(1.0)

    hour_bucket = df["submitted_at"].dt.floor("h")
    op_hour = df.groupby(["operator", hour_bucket]).operator.transform("size").astype(float)

    ckey = df["comment_hash"].where(df["comment_len"] >= config.repeated_comment_min_len)
    crep = ckey.map(ckey.value_counts()).fillna(1.0)

    feats = pd.DataFrame({
        "n_ratings": n,
        "mean_rating": mean,
        "std_rating": R.std(axis=1, ddof=0).fillna(0.0),
        "rating_range": rng,
        "share_extreme": extreme.fillna(0.0),
        "all_equal": ((n >= 3) & (rng == 0)).astype(float),
        "dev_from_operator_median": mean - mean.groupby(df["operator"]).transform("median"),
        "hour_sin": np.sin(2 * np.pi * hour / 24),
        "hour_cos": np.cos(2 * np.pi * hour / 24),
        "comment_len_log": np.log1p(df["comment_len"].astype(float)),
        "visitor_batch_count": vc.astype(float),
        "visitor_burst_count": window_counts(df["submitted_at"], gkey, config.visitor_burst_window_minutes * 60),
        "op_hour_volume": op_hour,
        "comment_repeat_count": crep.astype(float),
    }, index=df.index)
    return feats[FEATURE_COLUMNS].fillna(0.0)
