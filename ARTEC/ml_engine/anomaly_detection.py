"""Étape 3 : détection d'anomalies.

Référence : règles métier simples et explicables. Complément : Isolation Forest,
uniquement si le volume le justifie. LOF : comparaison optionnelle.

Un indicateur d'anomalie n'est PAS une preuve de fraude. Une panne réelle ou une
campagne de sondage légitime produit des concentrations : elles sont signalées
au niveau du GROUPE (avec le contexte), jamais comme faute individuelle.
"""
from __future__ import annotations

from typing import Dict, List, Optional

import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest
from sklearn.neighbors import LocalOutlierFactor
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import RobustScaler

from .features import FEATURE_COLUMNS
from .model_registry import ModelLoadError, ModelNotFoundError, ModelRegistry
from .schemas import EngineConfig

RULE_WEIGHTS = {"uniform_extreme_ratings": 0.5, "extreme_only_ratings": 0.5, "visitor_burst": 0.6, "repeated_comment": 0.4}


def _reason(code: str, message: str) -> dict:
    return {"code": code, "message": message}


# --------------------------------------------------------------------------
# Règles
# --------------------------------------------------------------------------
def apply_rules(df: pd.DataFrame, feats: pd.DataFrame, config: EngineConfig):
    reasons: Dict[object, List[dict]] = {i: [] for i in df.index}
    score = pd.Series(0.0, index=df.index)

    m = (feats["n_ratings"] >= 5) & (feats["all_equal"] == 1) & feats["mean_rating"].isin([config.rating_min, config.rating_max])
    for i in df.index[m]:
        reasons[i].append(_reason("uniform_extreme_ratings",
            "Toutes les notes renseignées sont identiques et extrêmes (≥5 critères). "
            "Peut être une opinion sincère très tranchée : à examiner, pas une preuve."))
    score[m] += RULE_WEIGHTS["uniform_extreme_ratings"]

    # Notes exclusivement extrêmes (0 ou 10) mais NON identiques : alternance 0/10, profil « tout ou rien ».
    # Complète la règle précédente (qui ne couvre que les notes toutes égales). Opinion tranchée possible : à examiner.
    m = (feats["n_ratings"] >= 5) & (feats["share_extreme"] >= 1.0) & (feats["all_equal"] == 0)
    for i in df.index[m]:
        reasons[i].append(_reason("extreme_only_ratings",
            "Toutes les notes renseignées sont extrêmes (0 ou 10) sans être identiques (≥5 critères) : profil de "
            "réponse peu plausible. Peut être une opinion sincère très tranchée : à examiner, pas une preuve."))
    score[m] += RULE_WEIGHTS["extreme_only_ratings"]

    m = feats["visitor_burst_count"] >= config.visitor_burst_threshold
    for i in df.index[m]:
        reasons[i].append(_reason("visitor_burst",
            f"≥{config.visitor_burst_threshold} soumissions du même visiteur (pseudonyme) pour le même "
            f"opérateur en {config.visitor_burst_window_minutes} min."))
    score[m] += RULE_WEIGHTS["visitor_burst"]

    m = feats["comment_repeat_count"] >= config.repeated_comment_threshold
    for i in df.index[m]:
        reasons[i].append(_reason("repeated_comment",
            f"Commentaire identique présent dans ≥{config.repeated_comment_threshold} observations du lot."))
    score[m] += RULE_WEIGHTS["repeated_comment"]

    return reasons, score.clip(upper=1.0)


def temporal_bursts(df: pd.DataFrame, feats: pd.DataFrame, config: EngineConfig) -> List[dict]:
    """Concentrations horaires par opérateur (niveau groupe uniquement).

    Référence robuste : médiane + MAD des volumes horaires de l'opérateur dans le lot ;
    échelle plancher sqrt(médiane) (comptage ~ Poisson) lorsque MAD = 0.
    """
    out = []
    hours = df["submitted_at"].dt.floor("h")
    for op, g in df.groupby("operator"):
        h = hours.loc[g.index]
        counts = h.value_counts().sort_index()
        full = pd.date_range(counts.index.min(), counts.index.max(), freq="h")
        if len(full) < config.burst_min_hours:
            continue
        counts = counts.reindex(full, fill_value=0)
        med = float(counts.median())
        mad = float((counts - med).abs().median())
        scale = max(1.4826 * mad, float(np.sqrt(max(med, 1.0))))
        z = (counts - med) / scale
        hot = counts[(z >= config.burst_z) & (counts >= config.burst_min_count)]
        for hh, c in hot.items():
            idx = g.index[h == hh]
            low = float((feats.loc[idx, "mean_rating"] < config.low_threshold).mean())
            out.append({
                "type": "temporal_burst", "operator": op, "hour_start": hh.isoformat(),
                "n_observations": int(c), "robust_z": round(float(z[hh]), 2),
                "baseline_median_per_hour": med, "share_low_mean_rating": round(low, 3),
                "n_distinct_visitors": int(df.loc[idx, "visitor_key"].nunique()),
                "obs_ids": df.loc[idx, "obs_id"].tolist(),
                "message": ("Volume horaire inhabituel. Interprétations possibles : panne réelle, campagne de "
                            "sondage légitime, ou soumissions concertées. Ne constitue pas une preuve de fraude."),
            })
    return out


def source_divergences(df: pd.DataFrame, feats: pd.DataFrame, config: EngineConfig) -> List[dict]:
    out = []
    for op, g in df.groupby("operator"):
        stats = feats.loc[g.index].groupby(g["source"])["mean_rating"].agg(["count", "mean"])
        stats = stats[stats["count"] >= config.min_n_reliable]
        if len(stats) >= 2 and stats["mean"].max() - stats["mean"].min() >= config.source_divergence_threshold:
            out.append({
                "type": "source_divergence", "operator": op,
                "sources": {s: {"n": int(r["count"]), "mean_rating": round(float(r["mean"]), 2)} for s, r in stats.iterrows()},
                "difference": round(float(stats["mean"].max() - stats["mean"].min()), 2),
                "message": "Écart important de moyenne entre sources comparables : biais de source possible (à examiner).",
            })
    return out


# --------------------------------------------------------------------------
# Isolation Forest / LOF
# --------------------------------------------------------------------------
def fit_isolation_forest(X: pd.DataFrame, config: EngineConfig) -> dict:
    pipe = Pipeline([
        ("scaler", RobustScaler()),
        ("iforest", IsolationForest(n_estimators=config.iforest_n_estimators, contamination="auto",
                                    random_state=config.random_state)),
    ])
    pipe.fit(X[FEATURE_COLUMNS].to_numpy())
    train_scores = -pipe.score_samples(X[FEATURE_COLUMNS].to_numpy())
    return {"pipeline": pipe, "feature_columns": list(FEATURE_COLUMNS), "n_train": int(len(X)),
            "train_score_quantile_95": float(np.quantile(train_scores, 0.95))}


def score_isolation_forest(bundle: dict, X: pd.DataFrame) -> np.ndarray:
    """Score brut -score_samples ∈ (0,1) : ≈0,5 = typique ; plus haut = plus inhabituel.
    Relatif à la distribution d'apprentissage : pas une probabilité."""
    missing = [c for c in bundle["feature_columns"] if c not in X.columns]
    if missing:
        raise ValueError(f"Variables manquantes pour le modèle : {missing}")
    return -bundle["pipeline"].score_samples(X[bundle["feature_columns"]].to_numpy())


def lof_scores(X: pd.DataFrame, n_neighbors: int = 20) -> np.ndarray:
    lof = LocalOutlierFactor(n_neighbors=max(2, min(n_neighbors, len(X) - 1)))
    lof.fit_predict(X[FEATURE_COLUMNS].to_numpy())
    return -lof.negative_outlier_factor_


def train_reference_model(X: pd.DataFrame, config: EngineConfig, registry: ModelRegistry, note: str = "") -> str:
    """Ajuste un Isolation Forest NON SUPERVISÉ sur un lot de référence validé par un humain et l'enregistre."""
    if len(X) < config.min_samples_isolation_forest:
        raise ValueError(f"Au moins {config.min_samples_isolation_forest} observations requises (reçu {len(X)}).")
    bundle = fit_isolation_forest(X, config)
    return registry.save("isolation_forest", bundle, {"type": "unsupervised", "n_train": len(X),
                                                      "note": note or "Aucune précision mesurée : pas de labels."})


# --------------------------------------------------------------------------
# Orchestration
# --------------------------------------------------------------------------
def detect(df: pd.DataFrame, feats: pd.DataFrame, config: EngineConfig, registry: Optional[ModelRegistry] = None) -> dict:
    warnings: List[dict] = []
    reasons, rule_score = apply_rules(df, feats, config)
    group_anoms = temporal_bursts(df, feats, config) + source_divergences(df, feats, config)

    iscore = pd.Series(np.nan, index=df.index)
    model_part = None
    bundle = None
    if registry is not None and config.use_registry_models:
        try:
            bundle, meta = registry.load("isolation_forest")
            model_part = f"iforest:{meta['version']}"
        except ModelNotFoundError:
            bundle = None
        except ModelLoadError as exc:
            warnings.append({"code": "model_load_failed",
                             "message": f"Modèle enregistré inutilisable ({exc}) : repli sur règles / modèle du lot."})
            bundle = None
    if bundle is None and len(feats) >= config.min_samples_isolation_forest:
        bundle = fit_isolation_forest(feats, config)
        model_part = "iforest:batch-fit"
        warnings.append({"code": "iforest_batch_reference",
                         "message": "Aucun modèle de référence : Isolation Forest ajusté sur le lot lui-même. "
                                    "Scores relatifs au lot, non comparables entre lots."})
    elif bundle is None:
        warnings.append({"code": "insufficient_data_for_ml",
                         "message": f"Moins de {config.min_samples_isolation_forest} observations valides : "
                                    "règles métier uniquement (pas d'Isolation Forest)."})

    if bundle is not None:
        try:
            iscore = pd.Series(score_isolation_forest(bundle, feats), index=df.index)
        except Exception as exc:
            warnings.append({"code": "iforest_scoring_failed", "message": f"Scoring Isolation Forest impossible : {exc}"})
            model_part = None

    stat_out = iscore.notna() & (iscore >= config.iforest_min_score)
    if stat_out.any() and bundle is not None:
        stat_out &= iscore >= bundle.get("train_score_quantile_95", 0.0)
    for i in df.index[stat_out]:
        reasons[i].append(_reason("statistical_outlier",
            f"Combinaison de variables statistiquement inhabituelle (score IF {iscore[i]:.2f}). Interprétation à valider par un agent."))

    method = "isolation_forest+rules" if model_part else "rules"
    anomaly_score = iscore.where(iscore.notna(), rule_score) if model_part else rule_score
    flagged = pd.Series([len(reasons[i]) > 0 for i in df.index], index=df.index)

    info = {"model_part": model_part, "method": method, "warnings": warnings}
    if config.compare_detectors and len(feats) >= max(50, 2):
        try:
            k = max(1, int(round(0.05 * len(feats))))
            lof = pd.Series(lof_scores(feats), index=df.index)
            top_lof = set(lof.nlargest(k).index)
            top_rules = set(rule_score.nlargest(k).index)
            top_if = set(iscore.nlargest(k).index) if iscore.notna().any() else set()
            jac = lambda a, b: round(len(a & b) / len(a | b), 3) if (a | b) else None
            info["detector_comparison"] = {"top_k": k, "jaccard_rules_lof": jac(top_rules, top_lof),
                                           "jaccard_iforest_lof": jac(top_if, top_lof),
                                           "jaccard_rules_iforest": jac(top_rules, top_if),
                                           "note": "Recouvrement entre méthodes ; ce n'est PAS une mesure de précision."}
        except Exception as exc:
            warnings.append({"code": "lof_failed", "message": str(exc)})

    per_obs = pd.DataFrame({"rule_score": rule_score, "iforest_score": iscore, "anomaly_score": anomaly_score,
                            "flagged": flagged}, index=df.index)
    per_obs["reasons"] = [reasons[i] for i in df.index]
    return {"per_obs": per_obs, "group_anomalies": group_anoms, "info": info}
