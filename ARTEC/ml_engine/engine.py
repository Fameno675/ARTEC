"""Moteur v0.1 : règles explicables + IsolationForest (scikit-learn) quand le lot est assez grand.

Ce moteur détecte des réponses ATYPIQUES. Il ne prouve ni fraude ni manipulation, et ne calcule
pas de probabilité d'authenticité (authenticity_probability = None).
"""
from datetime import datetime, timezone

import numpy as np

from .contract import (CONTRACT_VERSION, AnalysisError, AnalysisRequest, AnalysisResponse, ObservationResult, Reason)

MODEL_NAME = "rules_isolation_forest"
MODEL_VERSION = "0.1.0"


class IsolationForestEngine:
    def __init__(self, min_observations_for_model: int = 50, random_state: int = 42):
        self.min_obs = min_observations_for_model
        self.random_state = random_state

    def analyze(self, request: AnalysisRequest) -> AnalysisResponse:
        now = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
        if request.contract_version.split(".")[0] != CONTRACT_VERSION.split(".")[0]:
            return AnalysisResponse(request.batch_id, CONTRACT_VERSION, MODEL_NAME, MODEL_VERSION, "failed", [],
                                    [AnalysisError("unsupported_contract_version", request.contract_version)], now)
        obs = list(request.observations)
        results = {o.observation_id: ObservationResult(o.observation_id, False, None, None, []) for o in obs}
        errors = []

        for o in obs:  # règles explicables
            vals = [v for v in o.scores.values() if v is not None]
            r = results[o.observation_id]
            if len(vals) >= 3 and len(set(vals)) == 1:
                r.reasons.append(Reason("straight_lining", "Toutes les notes sont identiques.", None))
                r.is_anomaly = True
            if len(vals) >= 3 and all(v in (0, 10) for v in vals) and len(set(vals)) > 1:
                r.reasons.append(Reason("extreme_scores_only", "Uniquement des notes extrêmes (0 ou 10).", None))
                r.is_anomaly = True

        if len(obs) >= self.min_obs:
            try:
                self._run_model(obs, results)
            except Exception as exc:  # le modèle échoue : on garde les règles et on le signale
                errors.append(AnalysisError("model_error", f"{type(exc).__name__}: {exc}"))
        status = "partial" if errors else "succeeded"
        return AnalysisResponse(request.batch_id, CONTRACT_VERSION, MODEL_NAME, MODEL_VERSION, status,
                                list(results.values()), errors, now)

    def _run_model(self, obs, results):
        from sklearn.ensemble import IsolationForest

        codes = sorted({c for o in obs for c in o.scores})
        ops = np.array([o.operator_code for o in obs])
        X = np.full((len(obs), len(codes)), np.nan)
        for i, o in enumerate(obs):
            for j, c in enumerate(codes):
                v = o.scores.get(c)
                if v is not None:
                    X[i, j] = v
        # imputation par la moyenne de l'opérateur (sinon moyenne du lot, sinon 5)
        for op in set(ops):
            m = ops == op
            for j in range(len(codes)):
                col = X[m, j]
                fill = np.nanmean(col) if np.any(~np.isnan(col)) else (np.nanmean(X[:, j]) if np.any(~np.isnan(X[:, j])) else 5.0)
                col[np.isnan(col)] = fill
                X[m, j] = col
        n_scores = np.array([[sum(v is not None for v in o.scores.values())] for o in obs], dtype=float)
        feats = np.hstack([X, n_scores])
        model = IsolationForest(n_estimators=200, contamination="auto", random_state=self.random_state)
        model.fit(feats)
        raw = -model.score_samples(feats)  # score d'anomalie de l'article original, dans (0, 1)
        flags = model.predict(feats) == -1
        mu, sd = feats.mean(axis=0), feats.std(axis=0)
        sd[sd == 0] = 1.0
        z = np.abs((feats - mu) / sd)
        names = codes + ["n_scores"]
        for i, o in enumerate(obs):
            r = results[o.observation_id]
            r.anomaly_score = round(float(np.clip(raw[i], 0.0, 1.0)), 4)
            if flags[i]:
                r.is_anomaly = True
                j = int(np.argmax(z[i]))
                r.reasons.append(Reason("isolation_forest_outlier",
                                        "Combinaison de notes atypique par rapport au reste du lot.", names[j]))
