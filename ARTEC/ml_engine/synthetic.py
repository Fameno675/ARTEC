"""Jeu de données SYNTHÉTIQUE — FICTIF — uniquement pour tester le pipeline.

Ces données ne reflètent aucun opérateur réel. Les anomalies injectées servent à vérifier que le
code détecte ce qu'il est censé détecter ; elles ne permettent AUCUNE mesure de précision réelle.
Usage : python -m ml_engine.synthetic   (écrit tests/data/sample_fictif.csv)
"""
from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Tuple

import numpy as np
import pandas as pd

from .schemas import CRITERIA_KEYS, OPERATORS

_BASE = {  # moyennes fictives par critère
    "Orange Madagascar": [6.8, 6.4, 6.6, 7.0, 6.5, 7.1, 5.6, 6.5, 6.9, 6.0],
    "Yas Madagascar":    [6.0, 5.8, 6.1, 6.6, 6.2, 6.8, 5.9, 6.2, 6.4, 5.6],
    "Airtel Madagascar": [5.4, 5.0, 5.5, 6.0, 5.6, 6.5, 6.1, 5.8, 5.2, 5.3],
}
_WORDS = ["rapide", "lent", "correct", "instable", "cher", "fiable", "moyen", "bon", "mauvais", "coupure", "réseau",
          "forfait", "agence", "appel", "message", "recharge", "assistance", "débit", "village", "ville"]


def _row(rng, ts, op, source, visitor, ratings, comment):
    r = {"Identifiant avis": None, "Opérateur": op, "Source": source, "Date de soumission": ts.isoformat(),
         "ID visiteur": visitor, "Lot": "FICTIF-2026-09", "Commentaire": comment}
    r.update(dict(zip(CRITERIA_KEYS, ratings)))
    return r


def generate_synthetic(n: int = 1200, seed: int = 42, days: int = 28, start: str = "2026-09-01",
                       inject_anomalies: bool = True, inject_structural_errors: bool = True
                       ) -> Tuple[pd.DataFrame, Dict[str, List[str]]]:
    rng = np.random.default_rng(seed)
    t0 = pd.Timestamp(start, tz="UTC")
    hp = np.array([0.5] * 6 + [2] * 3 + [3] * 8 + [4] * 4 + [2] * 3, dtype=float)
    hp /= hp.sum()
    rows: List[dict] = []
    for _ in range(n):
        op = rng.choice(OPERATORS, p=[0.4, 0.33, 0.27])
        ts = t0 + pd.Timedelta(days=int(rng.integers(0, days)), hours=int(rng.choice(24, p=hp)),
                               minutes=int(rng.integers(0, 60)), seconds=int(rng.integers(0, 60)))
        vals = np.clip(np.round(rng.normal(_BASE[op], 1.8)), 0, 10)
        vals = np.where(rng.random(10) < 0.25, np.nan, vals)
        if np.isnan(vals).all():
            vals[int(rng.integers(0, 10))] = 6
        comment = None if rng.random() < 0.6 else " ".join(rng.choice(_WORDS, 4)) + f" #{int(rng.integers(0, 99999))}"
        rows.append(_row(rng, ts, op, rng.choice(["public_review", "survey", "operator_file"], p=[0.8, 0.12, 0.08]),
                         f"v{int(rng.integers(0, 900))}", vals, comment))
    truth: Dict[str, List[str]] = {"uniform_burst_yas": [], "outage_like_orange": [], "uniform_zero_airtel": [],
                                   "structural": []}
    if inject_anomalies:
        # (a) 40 notes 10/10 pour Yas par 3 visiteurs, même commentaire, en 40 minutes
        base = t0 + pd.Timedelta(days=10, hours=11)
        for j in range(40):
            rows.append(_row(rng, base + pd.Timedelta(minutes=j), "Yas Madagascar", "public_review",
                             f"vx{j % 3}", [10.0] * 10, "Le meilleur opérateur de Madagascar"))
            truth["uniform_burst_yas"].append(f"ROW{len(rows)}")
        # (b) 35 notes 0/10 pour Airtel, visiteurs distincts, une même heure (panne OU manipulation : indécidable ici)
        base = t0 + pd.Timedelta(days=15, hours=14)
        for j in range(35):
            rows.append(_row(rng, base + pd.Timedelta(minutes=int(rng.integers(0, 60))), "Airtel Madagascar",
                             "public_review", f"vz{j}", [0.0] * 10, None))
            truth["uniform_zero_airtel"].append(f"ROW{len(rows)}")
        # (c) panne plausible pour Orange : 30 avis bas MAIS variés, visiteurs distincts, même heure
        base = t0 + pd.Timedelta(days=20, hours=9)
        for j in range(30):
            rows.append(_row(rng, base + pd.Timedelta(minutes=int(rng.integers(0, 60))), "Orange Madagascar",
                             "public_review", f"vo{j}", np.clip(np.round(rng.normal(1.8, 1.0, 10)), 0, 10),
                             "Plus de réseau internet depuis ce matin " + str(j)))
            truth["outage_like_orange"].append(f"ROW{len(rows)}")
    if inject_structural_errors:
        ok_row = rows[0]
        dirty = []
        d = dict(ok_row); d[CRITERIA_KEYS[0]] = 11; dirty.append(("rating_out_of_range", d))
        d = dict(ok_row); d[CRITERIA_KEYS[1]] = -1; dirty.append(("rating_out_of_range", d))
        d = dict(ok_row); d["Opérateur"] = "Zain"; dirty.append(("unknown_operator", d))
        d = dict(ok_row); d["Date de soumission"] = "pas une date"; dirty.append(("invalid_date", d))
        d = dict(ok_row); d["Date de soumission"] = "2099-01-01T00:00:00+00:00"; dirty.append(("future_date", d))
        d = dict(ok_row); dirty.append(("exact_duplicate", d))
        d = dict(ok_row); d["Date de soumission"] = (pd.Timestamp(ok_row["Date de soumission"]) + pd.Timedelta(minutes=2)).isoformat()
        dirty.append(("probable_duplicate", d))
        d = dict(ok_row); d[CRITERIA_KEYS[2]] = "abc"; dirty.append(("non_numeric_value", d))
        d = dict(ok_row); d.update({k: None for k in CRITERIA_KEYS}); dirty.append(("no_ratings", d))
        for code, d in dirty:
            rows.append(d)
            truth["structural"].append(f"{code}@ROW{len(rows)}")
    df = pd.DataFrame(rows)
    df["Identifiant avis"] = [f"ROW{i + 1}" for i in range(len(df))]
    # ordre mélangé (comme un export réel) mais ids conservés
    df = df.sample(frac=1.0, random_state=seed).reset_index(drop=True)
    return df, truth


if __name__ == "__main__":
    out = Path(__file__).parent / "tests" / "data"
    out.mkdir(parents=True, exist_ok=True)
    df, truth = generate_synthetic()
    df.to_csv(out / "sample_fictif.csv", index=False, encoding="utf-8-sig")
    pd.Series({k: ";".join(v) for k, v in truth.items()}).to_json(out / "sample_fictif_truth.json", indent=2, force_ascii=False)
    print(f"{len(df)} lignes FICTIVES écrites dans {out}")
