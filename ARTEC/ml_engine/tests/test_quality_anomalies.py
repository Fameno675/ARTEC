import numpy as np
import pandas as pd
from ml_engine.features import build_features
from ml_engine.anomaly_detection import detect
from ml_engine.preprocessing import preprocess
from ml_engine.quality_scoring import compute_quality, dimension_scores
from ml_engine.schemas import EngineConfig
from ml_engine.validation import validate


def _valid(synth, cfg):
    raw, truth = synth
    clean, _ = preprocess(raw, cfg)
    val, _ = validate(clean, cfg)
    return val[val.validation_status != "rejected"], truth


def test_dimension_score_arithmetic_and_weights(cfg):
    df = pd.DataFrame({"operator": ["Orange Madagascar"] * 2,
                       "internet_vitesse": [8.0, 6.0], "internet_stabilite": [4.0, np.nan],
                       "internet_disponibilite": [np.nan, np.nan]})
    for c in ["appels_qualite_sonore", "appels_reussite", "sms_fiabilite", "tarification", "credit_forfaits",
              "mobile_money", "service_client"]:
        df[c] = np.nan
    d = dimension_scores(df, cfg)
    assert d["dim_internet"].tolist()[0] == 6.0 and d["dim_internet"].tolist()[1] == 6.0
    w = EngineConfig(criterion_weights={"internet_vitesse": 3.0})
    assert dimension_scores(df, w)["dim_internet"].iloc[0] == (8 * 3 + 4) / 4
    assert np.isnan(d["dim_appels"].iloc[0])           # pas de note -> pas de score inventé


def test_quality_reproducible_and_flags_small_samples(synth, cfg):
    v, _ = _valid(synth, cfg)
    a, b = compute_quality(v, cfg), compute_quality(v, cfg)
    assert a == b
    small = v[v.operator == "Orange Madagascar"].head(10)
    q = compute_quality(small, cfg)
    assert q["by_operator"]["Orange Madagascar"]["dimensions"]["internet"]["reliable_sample"] is False
    assert any(w["code"] == "small_sample" for w in q["warnings"])


def test_shares_sum_to_one(synth, cfg):
    v, _ = _valid(synth, cfg)
    s = compute_quality(v, cfg)["by_operator"]["Yas Madagascar"]["criteria"]["tarification"]
    assert abs(s["share_low"] + s["share_mid"] + s["share_high"] - 1) < 0.01


def test_rules_catch_injected_patterns_but_not_plausible_outage(synth, cfg):
    v, truth = _valid(synth, cfg)
    f = build_features(v, cfg)
    det = detect(v, f, cfg, None)
    flagged = set(v.loc[det["per_obs"].index[det["per_obs"].flagged], "obs_id"])
    assert set(truth["uniform_burst_yas"]) <= flagged
    assert set(truth["uniform_zero_airtel"]) <= flagged
    assert not (set(truth["outage_like_orange"]) & flagged)        # panne plausible : pas de faute individuelle
    ops = {g["operator"] for g in det["group_anomalies"] if g["type"] == "temporal_burst"}
    assert {"Orange Madagascar", "Airtel Madagascar", "Yas Madagascar"} <= ops   # signalée au niveau groupe
    assert all("preuve" in g["message"] for g in det["group_anomalies"] if g["type"] == "temporal_burst")


def test_small_batch_uses_rules_only(synth, cfg):
    v, _ = _valid(synth, cfg)
    v = v.head(60)
    det = detect(v, build_features(v, cfg), cfg, None)
    assert det["info"]["method"] == "rules"
    assert any(w["code"] == "insufficient_data_for_ml" for w in det["info"]["warnings"])
