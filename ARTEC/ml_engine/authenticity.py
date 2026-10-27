"""Étape 4 : classification supervisée de l'authenticité — UNIQUEMENT si des labels vérifiés existent.

Sans labels : le moteur ne produit aucune probabilité d'authenticité (voir prediction.py).
Ce module fournit l'outillage d'évaluation à utiliser le jour où des labels fiables existent.
Convention : label 1 = non fiable, 0 = fiable.
"""
from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd
from sklearn.calibration import CalibratedClassifierCV, calibration_curve
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import brier_score_loss, confusion_matrix, precision_recall_fscore_support
from sklearn.model_selection import GroupShuffleSplit
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import RobustScaler

from .features import FEATURE_COLUMNS
from .model_registry import ModelRegistry
from .schemas import EngineConfig


class InsufficientLabelsError(ValueError):
    pass


def _metrics(y, pred, proba=None) -> dict:
    p, r, f, _ = precision_recall_fscore_support(y, pred, average="binary", pos_label=1, zero_division=0)
    tn, fp, fn, tp = confusion_matrix(y, pred, labels=[0, 1]).ravel()
    out = {"n": int(len(y)), "precision": round(float(p), 4), "recall": round(float(r), 4), "f1": round(float(f), 4),
           "confusion_matrix": {"tn": int(tn), "fp": int(fp), "fn": int(fn), "tp": int(tp)},
           "false_positive_rate": round(float(fp / (fp + tn)), 4) if (fp + tn) else None,
           "false_negative_rate": round(float(fn / (fn + tp)), 4) if (fn + tp) else None}
    if proba is not None:
        out["brier"] = round(float(brier_score_loss(y, proba)), 4)
    return out


def train_supervised(feats: pd.DataFrame, labels: pd.Series, config: EngineConfig, *,
                     groups: Optional[pd.Series] = None, times: Optional[pd.Series] = None,
                     meta: Optional[pd.DataFrame] = None, kind: str = "logreg",
                     registry: Optional[ModelRegistry] = None, test_size: float = 0.25):
    """Entraîne et évalue. Séparation par GROUPES (lot/campagne) ou TEMPORELLE : jamais aléatoire simple,
    pour éviter les fuites entre observations d'un même lot. Retourne (bundle, rapport)."""
    labels = labels.dropna().astype(int)
    feats = feats.loc[labels.index]
    if len(labels) < config.supervised_min_labeled:
        raise InsufficientLabelsError(f"{len(labels)} labels < minimum {config.supervised_min_labeled}.")
    vc = labels.value_counts()
    if len(vc) < 2 or vc.min() < config.supervised_min_per_class:
        raise InsufficientLabelsError(f"Effectifs par classe insuffisants : {vc.to_dict()}.")
    if groups is None and times is None:
        raise ValueError("Fournir `groups` (lot/campagne) ou `times` : une séparation aléatoire simple est refusée (fuite).")

    if groups is not None:
        g = groups.loc[labels.index]
        if g.nunique() < 2:
            raise InsufficientLabelsError("Au moins 2 groupes (lots/campagnes) sont nécessaires.")
        tr, te = next(GroupShuffleSplit(n_splits=1, test_size=test_size, random_state=config.random_state)
                      .split(feats, labels, g))
        split = "group"
        tr_idx, te_idx = feats.index[tr], feats.index[te]
    else:
        order = times.loc[labels.index].sort_values().index
        cut = int(len(order) * (1 - test_size))
        tr_idx, te_idx = order[:cut], order[cut:]
        split = "temporal"
    ytr, yte = labels.loc[tr_idx], labels.loc[te_idx]
    if ytr.nunique() < 2 or yte.nunique() < 2:
        raise InsufficientLabelsError("Les deux classes doivent exister dans l'entraînement ET dans le test.")

    X = feats[FEATURE_COLUMNS]
    if kind == "rf":
        base = RandomForestClassifier(n_estimators=300, min_samples_leaf=3, class_weight="balanced",
                                      random_state=config.random_state)
    else:
        base = make_pipeline(RobustScaler(), LogisticRegression(class_weight="balanced", max_iter=1000))
    model = CalibratedClassifierCV(base, cv=3, method="sigmoid")
    model.fit(X.loc[tr_idx], ytr)
    proba = model.predict_proba(X.loc[te_idx])[:, 1]
    pred = (proba >= 0.5).astype(int)

    report = {"model": kind, "split": split, "n_train": int(len(tr_idx)), "n_test": int(len(te_idx)),
              "class_balance_test": {str(k): int(v) for k, v in yte.value_counts().items()},
              **_metrics(yte, pred, proba)}
    try:
        pt, pp = calibration_curve(yte, proba, n_bins=5, strategy="quantile")
        report["calibration_curve"] = {"prob_true": pt.round(3).tolist(), "prob_pred": pp.round(3).tolist()}
    except Exception:
        report["calibration_curve"] = None
    if meta is not None:
        for col in ("source", "operator"):
            if col in meta:
                sub = {}
                for val, idx in meta.loc[te_idx].groupby(col).groups.items():
                    yy = yte.loc[idx]
                    if len(yy) >= config.min_n_reliable and yy.nunique() == 2:
                        pr = pd.Series(pred, index=te_idx).loc[idx]
                        sub[str(val)] = _metrics(yy, pr)
                    else:
                        sub[str(val)] = {"n": int(len(yy)), "note": "effectif insuffisant"}
                report[f"by_{col}"] = sub
    report["qualified"] = bool(report["n_test"] >= 100 and report["f1"] >= config.supervised_min_f1)
    report["notes"] = ["Qualification = seuil technique minimal fixé par la config ; la mise en service "
                       "relève d'une validation humaine (faux positifs / faux négatifs à examiner)."]

    bundle = {"model": model, "feature_columns": list(FEATURE_COLUMNS), "threshold": 0.5}
    if registry is not None:
        version = registry.save("authenticity", bundle, {"type": "supervised", "evaluation": report,
                                                         "qualified": report["qualified"], "calibrated": True},
                                set_latest=report["qualified"])
        report["registry_version"] = version
    return bundle, report


def predict_unreliable_proba(bundle: dict, feats: pd.DataFrame) -> np.ndarray:
    return bundle["model"].predict_proba(feats[bundle["feature_columns"]])[:, 1]
