"""Interface stable : analyze_batch(data, metadata=None, config=None, registry=None) -> dict JSON-sérialisable.

Garanties :
- ne lève jamais d'exception (toute erreur est renvoyée dans `errors`, statut 'failed' ou 'partial') ;
- une erreur ML ne supprime pas les résultats de validation / de scores déjà calculés ;
- aucune sanction ni permission ici : le backend Django enregistre et présente ;
- `authenticity_probability` n'est émis QUE si un modèle supervisé calibré ET qualifié est enregistré.
"""
from __future__ import annotations

import math
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import numpy as np
import pandas as pd

from . import anomaly_detection as ad
from .authenticity import predict_unreliable_proba
from .features import build_features
from .model_registry import ModelLoadError, ModelNotFoundError, ModelRegistry
from .preprocessing import SchemaError, load_input, preprocess
from .quality_scoring import compute_quality
from .schemas import ENGINE_VERSION, EngineConfig
from .validation import REASON_MESSAGES, profile_batch, validate


def to_jsonable(o: Any):
    if isinstance(o, dict):
        return {str(k): to_jsonable(v) for k, v in o.items()}
    if isinstance(o, (list, tuple, set)):
        return [to_jsonable(v) for v in o]
    if isinstance(o, (pd.Timestamp, datetime)):
        return None if pd.isna(o) else o.isoformat()
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating, float)):
        f = float(o)
        return None if math.isnan(f) or math.isinf(f) else f
    if isinstance(o, np.bool_):
        return bool(o)
    if isinstance(o, Path):
        return str(o)
    if o is pd.NaT:
        return None
    return o


def _msg(code: str) -> dict:
    return {"code": code, "message": REASON_MESSAGES.get(code, code)}


def analyze_batch(data, metadata: Optional[dict] = None, config: Optional[EngineConfig] = None,
                  registry: Optional[ModelRegistry] = None) -> dict:
    """Analyse un lot déjà validé/importé. Voir docs/README.md pour le contrat complet."""
    config = config or EngineConfig()
    metadata = dict(metadata or {})
    batch_id = str(metadata.get("batch_id") or uuid.uuid4())
    res = {
        "batch_id": batch_id, "engine_version": ENGINE_VERSION, "model_version": f"rules-{ENGINE_VERSION}",
        "analysis_date": datetime.now(timezone.utc).isoformat(), "status": "ok",
        "metadata": {k: v for k, v in metadata.items() if k != "batch_id"},
        "total_observations": 0, "accepted_observations": 0, "review_observations": 0,
        "valid_observations": 0, "rejected_observations": 0,
        "profile": None, "preprocessing_log": [], "validation_report": None,
        "reference_period": None, "quality_scores": None, "trend": None, "comparisons": None,
        "anomalies": [], "group_anomalies": [], "rejected": [], "observation_results": [],
        "authenticity": {"supervised_model_used": False,
                         "note": "Aucun modèle supervisé qualifié : pas de probabilité d'authenticité. "
                                 "'no_anomaly_detected' ne signifie PAS 'authentique'."},
        "representativity_notes": [], "warnings": [], "errors": [],
    }
    try:
        _run(data, metadata, config, registry, res)
    except Exception as exc:  # filet de sécurité final : jamais d'exception vers Django
        res["errors"].append({"code": "unexpected_error", "message": f"{type(exc).__name__}: {exc}"})
        res["status"] = "failed" if res["total_observations"] == 0 else "partial"
    if res["status"] == "ok" and res["warnings"]:
        res["status"] = "ok_with_warnings"
    return to_jsonable(res)


def _run(data, metadata, config, registry, res):
    # ---- chargement + prétraitement (échec = lot inanalysable)
    try:
        raw = load_input(data)
        clean, log = preprocess(raw, config)
    except SchemaError as exc:
        res["errors"].append({"code": "schema_error", "message": str(exc)})
        res["status"] = "failed"
        return
    except Exception as exc:
        res["errors"].append({"code": "input_error", "message": f"{type(exc).__name__}: {exc}"})
        res["status"] = "failed"
        return
    res["preprocessing_log"] = log
    res["total_observations"] = int(len(clean))

    # ---- validation structurelle
    val, vrep = validate(clean, config)
    res["validation_report"] = vrep
    res["accepted_observations"] = vrep["accepted"]
    res["review_observations"] = vrep["review"]
    res["rejected_observations"] = vrep["rejected"]
    res["valid_observations"] = vrep["accepted"] + vrep["review"]
    try:
        res["profile"] = profile_batch(raw, clean, config)
    except Exception as exc:
        res["warnings"].append({"code": "profile_failed", "message": str(exc)})

    rej = val[val["validation_status"] == "rejected"]
    res["rejected"] = [{"obs_id": r.obs_id, "row_number": int(r.row_number),
                        "reasons": [_msg(c) for c in r.validation_reasons]} for r in rej.itertuples()]
    ok = val[val["validation_status"] != "rejected"]
    if ok.empty:
        res["warnings"].append({"code": "no_valid_observation", "message": "Aucune observation valide dans le lot."})
        res["observation_results"] = _obs_results(val, None, None, False)
        return

    # ---- scores de qualité (indépendants du ML)
    scoped = ok if config.include_review_in_scores else ok[ok["validation_status"] == "accepted"]
    p_start = metadata.get("period_start") or config.period_start
    p_end = metadata.get("period_end") or config.period_end
    if p_start:
        scoped = scoped[scoped["submitted_at"] >= pd.Timestamp(p_start, tz="UTC")]
    if p_end:
        scoped = scoped[scoped["submitted_at"] <= pd.Timestamp(p_end, tz="UTC")]
    res["reference_period"] = {
        "start": (pd.Timestamp(p_start, tz="UTC") if p_start else scoped["submitted_at"].min()),
        "end": (pd.Timestamp(p_end, tz="UTC") if p_end else scoped["submitted_at"].max()),
        "defined_by": "configuration/metadata" if (p_start or p_end) else "étendue du lot (par défaut)",
        "n_observations_in_period": int(len(scoped)),
    }
    quality_ok = False
    try:
        q = compute_quality(scoped, config)
        res["quality_scores"] = q["by_operator"]
        res["trend"], res["comparisons"] = q["trend"], q["comparisons"]
        res["representativity_notes"] = q["representativity_notes"]
        res["warnings"].extend(q["warnings"])
        quality_ok = True
    except Exception as exc:
        res["errors"].append({"code": "quality_scoring_failed", "message": f"{type(exc).__name__}: {exc}"})
        res["status"] = "partial"

    # ---- détection d'anomalies + authenticité (erreur ML => partial, données conservées)
    det = feats = proba = None
    ml_ok = False
    try:
        feats = build_features(ok, config)
        reg = registry if registry is not None else (ModelRegistry() if config.use_registry_models else None)
        det = ad.detect(ok, feats, config, reg)
        res["warnings"].extend(det["info"]["warnings"])
        if det["info"]["model_part"]:
            res["model_version"] = f"rules-{ENGINE_VERSION}+{det['info']['model_part']}"
        res["group_anomalies"] = det["group_anomalies"]
        if "detector_comparison" in det["info"]:
            res["detector_comparison"] = det["info"]["detector_comparison"]
        ml_ok = True
        # modèle supervisé : seulement s'il existe, est calibré et qualifié
        if reg is not None and config.use_registry_models:
            try:
                bundle, meta = reg.load("authenticity")
                if meta.get("qualified") and meta.get("calibrated"):
                    proba = pd.Series(predict_unreliable_proba(bundle, feats), index=ok.index)
                    res["authenticity"] = {"supervised_model_used": True, "model_version": meta["version"],
                                           "threshold": bundle.get("threshold", 0.5),
                                           "note": "Probabilité estimée d'être NON FIABLE, issue d'un modèle évalué ; "
                                                   "outil d'aide, jamais une décision. Voir le rapport d'évaluation."}
                    res["model_version"] += f"+authenticity:{meta['version']}"
            except ModelNotFoundError:
                pass
            except (ModelLoadError, Exception) as exc:
                res["warnings"].append({"code": "authenticity_model_unusable", "message": str(exc)})
    except Exception as exc:
        res["errors"].append({"code": "ml_stage_failed",
                              "message": f"{type(exc).__name__}: {exc}. Les données validées restent exploitables."})
        res["status"] = "partial"

    res["observation_results"] = _obs_results(val, det, proba, ml_ok, res["authenticity"])
    if det is not None:
        by_id = {r["obs_id"]: r for r in res["observation_results"]}
        for i in det["per_obs"].index[det["per_obs"]["flagged"]]:
            row = ok.loc[i]
            f = feats.loc[i]
            res["anomalies"].append({
                "obs_id": row["obs_id"], "row_number": int(row["row_number"]), "operator": row["operator"],
                "anomaly_score": det["per_obs"].at[i, "anomaly_score"],
                "anomaly_method": det["info"]["method"], "reasons": det["per_obs"].at[i, "reasons"],
                "evidence": {k: f[k] for k in ("n_ratings", "mean_rating", "visitor_burst_count",
                                               "op_hour_volume", "comment_repeat_count")},
                "authenticity_status": by_id[row["obs_id"]]["authenticity_status"],
            })
    return


def _obs_results(val, det, proba, ml_ok, auth=None):
    out = []
    thr = (auth or {}).get("threshold", 0.5)
    for i, r in val.iterrows():
        reasons = [_msg(c) for c in r["validation_reasons"]]
        score, method, status, p = None, None, None, None
        if r["validation_status"] == "rejected":
            status = "rejected_structural"
        elif not ml_ok or det is None:
            status = "needs_review" if r["validation_status"] == "review" else "not_assessed"
        else:
            score = det["per_obs"].at[i, "anomaly_score"]
            method = det["info"]["method"]
            reasons += det["per_obs"].at[i, "reasons"]
            flagged = bool(det["per_obs"].at[i, "flagged"]) or r["validation_status"] == "review"
            status = "needs_review" if flagged else "no_anomaly_detected"
            if proba is not None:
                p = float(proba.at[i])
                if p >= thr:
                    status = "model_flagged_unreliable"
        item = {"obs_id": r["obs_id"], "row_number": int(r["row_number"]), "operator": r["operator"],
                "validation_status": r["validation_status"], "authenticity_status": status,
                "anomaly_score": score, "anomaly_method": method, "reasons": reasons}
        if p is not None:  # champ présent UNIQUEMENT avec un modèle supervisé qualifié
            item["authenticity_probability"] = p
        out.append(item)
    return out
