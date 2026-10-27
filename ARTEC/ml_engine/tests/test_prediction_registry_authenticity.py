import json
import numpy as np
import pandas as pd
import pytest
from ml_engine import analyze_batch, EngineConfig
from ml_engine import prediction
from ml_engine.authenticity import InsufficientLabelsError, train_supervised
from ml_engine.model_registry import ModelIntegrityError, ModelNotFoundError, ModelRegistry
from ml_engine.schemas import AUTHENTICITY_STATUSES


def _has_key(o, key):
    if isinstance(o, dict):
        return key in o or any(_has_key(v, key) for v in o.values())
    if isinstance(o, list):
        return any(_has_key(v, key) for v in o)
    return False


def test_contract_json_and_no_probability_without_supervised_model(synth, cfg, tmp_path):
    raw, _ = synth
    res = analyze_batch(raw, {"batch_id": "T1"}, cfg, ModelRegistry(tmp_path))
    json.dumps(res, allow_nan=False)                                 # sérialisable strict
    assert res["batch_id"] == "T1" and res["model_version"].startswith("rules-")
    assert res["total_observations"] == len(raw)
    assert res["valid_observations"] + res["rejected_observations"] == len(raw)
    assert not _has_key(res, "authenticity_probability")
    assert {o["authenticity_status"] for o in res["observation_results"]} <= set(AUTHENTICITY_STATUSES)
    assert res["authenticity"]["supervised_model_used"] is False
    assert all(a["reasons"] and a["evidence"] for a in res["anomalies"])      # consultable par l'agent


def test_deterministic(synth, cfg, tmp_path):
    raw, _ = synth
    reg = ModelRegistry(tmp_path)
    a = analyze_batch(raw, {"batch_id": "X"}, cfg, reg)
    b = analyze_batch(raw, {"batch_id": "X"}, cfg, reg)
    for r in (a, b):
        r.pop("analysis_date")
    assert a == b


def test_schema_error_returns_failed_without_raising(cfg):
    res = analyze_batch(pd.DataFrame({"x": [1]}), None, cfg)
    assert res["status"] == "failed" and res["errors"][0]["code"] == "schema_error"
    assert analyze_batch("fichier_inexistant.csv", None, cfg)["status"] == "failed"


def test_ml_failure_keeps_validated_results(synth, cfg, monkeypatch, tmp_path):
    raw, _ = synth
    monkeypatch.setattr(prediction, "build_features", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    res = analyze_batch(raw, None, cfg, ModelRegistry(tmp_path))
    assert res["status"] == "partial"
    assert any(e["code"] == "ml_stage_failed" for e in res["errors"])
    assert res["valid_observations"] > 0 and res["quality_scores"] is not None
    assert {o["authenticity_status"] for o in res["observation_results"]} <= {"not_assessed", "needs_review", "rejected_structural"}


def test_corrupted_model_falls_back(synth, tmp_path):
    from ml_engine.anomaly_detection import fit_isolation_forest
    from ml_engine.features import build_features
    from ml_engine.preprocessing import preprocess
    from ml_engine.validation import validate
    cfg = EngineConfig(reference_now="2026-10-25T00:00:00+00:00")
    raw, _ = synth
    v, _ = validate(*[preprocess(raw, cfg)[0], cfg])
    reg = ModelRegistry(tmp_path)
    ver = reg.save("isolation_forest", fit_isolation_forest(build_features(v[v.validation_status != "rejected"], cfg), cfg))
    (tmp_path / "isolation_forest" / ver / "model.joblib").write_bytes(b"corrompu")
    res = analyze_batch(raw, None, cfg, reg)
    assert res["status"] in ("ok_with_warnings", "ok")
    assert any(w["code"] == "model_load_failed" for w in res["warnings"])
    assert res["valid_observations"] > 0


def test_registry_roundtrip_integrity_and_rollback(tmp_path):
    reg = ModelRegistry(tmp_path)
    with pytest.raises(ModelNotFoundError):
        reg.load("m")
    v1 = reg.save("m", {"a": 1}, {"note": "v1"})
    v2 = reg.save("m", {"a": 2})
    assert reg.load("m")[0] == {"a": 2}
    reg.set_latest("m", v1)                                    # retour arrière
    assert reg.load("m")[0] == {"a": 1}
    (tmp_path / "m" / v2 / "model.joblib").write_bytes(b"x")
    with pytest.raises(ModelIntegrityError):
        reg.load("m", v2)


def test_supervised_refuses_without_labels_or_leak_safe_split(cfg):
    X = pd.DataFrame(np.random.default_rng(0).normal(size=(50, 14)), columns=__import__("ml_engine.features", fromlist=["x"]).FEATURE_COLUMNS)
    with pytest.raises(InsufficientLabelsError):
        train_supervised(X, pd.Series([0, 1] * 25, index=X.index), cfg, groups=pd.Series(range(50), index=X.index))
    Xb = pd.concat([X] * 8, ignore_index=True)
    y = pd.Series([0, 1] * 200, index=Xb.index)
    with pytest.raises(ValueError):
        train_supervised(Xb, y, cfg)                            # ni groupes ni temps : refusé


def test_supervised_mechanics_on_artificial_labels(cfg, tmp_path):
    """Teste la MÉCANIQUE d'évaluation sur des labels artificiels ; ne mesure aucune performance réelle."""
    from ml_engine.features import FEATURE_COLUMNS
    rng = np.random.default_rng(1)
    n = 600
    y = pd.Series(rng.integers(0, 2, n))
    X = pd.DataFrame(rng.normal(size=(n, len(FEATURE_COLUMNS))), columns=FEATURE_COLUMNS)
    X["mean_rating"] += y * 1.5
    groups = pd.Series(rng.integers(0, 12, n))
    meta = pd.DataFrame({"source": "public_review", "operator": "Orange Madagascar"}, index=X.index)
    reg = ModelRegistry(tmp_path)
    bundle, rep = train_supervised(X, y, cfg, groups=groups, meta=meta, registry=reg)
    for k in ("precision", "recall", "f1", "confusion_matrix", "brier", "calibration_curve", "split", "qualified"):
        assert k in rep
    assert rep["split"] == "group" and "by_source" in rep
