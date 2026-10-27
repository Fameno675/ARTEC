import pandas as pd
import pytest
from ml_engine.preprocessing import SchemaError, norm_name, preprocess
from ml_engine.schemas import EngineConfig
from ml_engine.validation import validate


def _mini(**over):
    row = {"Opérateur": "orange", "Date": "2026-09-01T10:00:00+03:00", "id visiteur": "abc",
           "Commentaire": "Très bien", "internet_vitesse": "7,5", "service_client": 8}
    row.update(over)
    return pd.DataFrame([row])


def test_norm_name_accents():
    assert norm_name("Opérateur ") == "operateur"
    assert norm_name("Date de soumission") == "date_de_soumission"


def test_preprocess_normalizes_and_minimizes_personal_data(cfg):
    df, log = preprocess(_mini(), cfg)
    assert df.loc[0, "operator"] == "Orange Madagascar"
    assert df.loc[0, "internet_vitesse"] == 7.5          # virgule décimale
    assert "visitor_id" not in df.columns and "comment" not in df.columns
    assert len(df.loc[0, "visitor_key"]) == 16 and df.loc[0, "visitor_key"] != "abc"
    assert pd.isna(df.loc[0, "mobile_money"])            # non imputé
    assert any(s["step"] == "pseudonymize_visitor" for s in log)


def test_missing_required_columns_raises(cfg):
    with pytest.raises(SchemaError):
        preprocess(pd.DataFrame({"foo": [1]}), cfg)
    with pytest.raises(SchemaError):
        preprocess(pd.DataFrame({"operateur": ["orange"], "date": ["2026-09-01"]}), cfg)  # aucun critère


def test_validation_flags_expected_cases_and_drops_nothing(synth, cfg):
    raw, truth = synth
    clean, _ = preprocess(raw, cfg)
    val, rep = validate(clean, cfg)
    assert len(val) == len(raw)                                   # aucune suppression silencieuse
    assert rep["accepted"] + rep["review"] + rep["rejected"] == len(raw)
    by_id = val.set_index("obs_id")["validation_reasons"]
    for item in truth["structural"]:
        code, rid = item.split("@")
        if code == "probable_duplicate":
            assert code in by_id[rid]
        elif code != "exact_duplicate":     # la copie exacte porte un nouvel id : testée via le décompte
            assert code in by_id[rid], item
    assert rep["reason_counts"]["exact_duplicate"] == 1
    st = val.set_index("obs_id")["validation_status"]
    assert st[[i.split("@")[1] for i in truth["structural"] if i.startswith("rating_out")][0]] == "rejected"


def test_nonnumeric_is_review_not_reject(cfg):
    df, _ = preprocess(_mini(service_client="abc"), cfg)
    val, _ = validate(df, cfg)
    assert val.loc[0, "validation_status"] == "review"
    assert "non_numeric_value" in val.loc[0, "validation_reasons"]


def test_out_of_range_rejected(cfg):
    df, _ = preprocess(_mini(internet_vitesse=11), cfg)
    val, _ = validate(df, cfg)
    assert val.loc[0, "validation_status"] == "rejected"
