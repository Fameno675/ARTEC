"""Contrat d'intégration backend <-> moteur ML, version 1.0 (transport-agnostique).

Définitions (ne jamais les confondre) :
- quality_score : moyenne des notes 0-10, calculée par le backend (apps.analytics). Le ML n'y touche pas.
- anomaly_score : 0-1, plus haut = plus atypique. CE N'EST PAS UNE PROBABILITÉ.
- authenticity_probability : 0-1, uniquement si le modèle est calibré pour cela ; sinon None.
Une prédiction ne déclenche jamais de sanction : examen humain obligatoire.
"""
from dataclasses import dataclass, field
from typing import Literal, Protocol

CONTRACT_VERSION = "1.0"


@dataclass(frozen=True)
class Observation:
    observation_id: str
    operator_code: str
    collected_at: str  # AAAA-MM-JJ
    source: str
    scores: dict  # code du critère -> entier 0-10 ou None


@dataclass(frozen=True)
class AnalysisRequest:
    batch_id: str
    contract_version: str
    observations: list


@dataclass
class Reason:
    code: str
    message: str
    feature: str | None = None


@dataclass
class ObservationResult:
    observation_id: str
    is_anomaly: bool | None
    anomaly_score: float | None
    authenticity_probability: float | None
    reasons: list = field(default_factory=list)


@dataclass
class AnalysisError:
    code: str
    message: str
    observation_id: str | None = None


@dataclass
class AnalysisResponse:
    batch_id: str
    contract_version: str
    model_name: str
    model_version: str
    status: Literal["succeeded", "partial", "failed"]
    results: list
    errors: list
    processed_at: str


class AnomalyEngine(Protocol):
    def analyze(self, request: AnalysisRequest) -> AnalysisResponse: ...
