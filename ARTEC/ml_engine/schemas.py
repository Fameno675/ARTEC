"""Schémas, constantes et configuration du moteur ML ARTEC.

Tout ce qui est "métier" (opérateurs, critères, seuils, poids) est ici et
configurable via EngineConfig : rien n'est codé en dur ailleurs.
"""
from __future__ import annotations

from dataclasses import dataclass, field, fields
from typing import Callable, Dict, List, Optional

ENGINE_VERSION = "1.0.0"

# --------------------------------------------------------------------------
# Opérateurs
# --------------------------------------------------------------------------
OPERATORS = ("Orange Madagascar", "Yas Madagascar", "Airtel Madagascar")

# Clés déjà normalisées (minuscules, sans accents). Extensible.
OPERATOR_ALIASES: Dict[str, str] = {
    "orange": "Orange Madagascar",
    "orange madagascar": "Orange Madagascar",
    "orange mg": "Orange Madagascar",
    "yas": "Yas Madagascar",
    "yas madagascar": "Yas Madagascar",
    "yas mg": "Yas Madagascar",
    "telma": "Yas Madagascar",  # alias historique : à valider par le métier
    "airtel": "Airtel Madagascar",
    "airtel madagascar": "Airtel Madagascar",
    "airtel mg": "Airtel Madagascar",
}

SOURCES = ("public_review", "operator_file", "survey", "external", "complaint")

# --------------------------------------------------------------------------
# Critères (notes 0-10, perception déclarée) et dimensions
# --------------------------------------------------------------------------
CRITERIA: Dict[str, tuple] = {
    "internet_vitesse": ("Internet mobile : vitesse ressentie de téléchargement", "internet"),
    "internet_stabilite": ("Internet mobile : stabilité de la connexion", "internet"),
    "internet_disponibilite": ("Internet mobile : disponibilité de la connexion", "internet"),
    "appels_qualite_sonore": ("Appels : qualité sonore", "appels"),
    "appels_reussite": ("Appels : réussite et stabilité des appels", "appels"),
    "sms_fiabilite": ("SMS : fiabilité et rapidité de réception", "sms"),
    "tarification": ("Tarification : rapport qualité-prix des forfaits", "tarification"),
    "credit_forfaits": ("Crédit et forfaits : facilité d'achat et de renouvellement", "credit_forfaits"),
    "mobile_money": ("Mobile money : fiabilité des transactions", "mobile_money"),
    "service_client": ("Service client : rapidité et qualité de l'assistance", "service_client"),
}
CRITERIA_KEYS: List[str] = list(CRITERIA)

DIMENSIONS: Dict[str, List[str]] = {}
for _k, (_label, _dim) in CRITERIA.items():
    DIMENSIONS.setdefault(_dim, []).append(_k)

# --------------------------------------------------------------------------
# Colonnes d'entrée
# --------------------------------------------------------------------------
REQUIRED_COLUMNS = ("operator", "submitted_at")  # + au moins un critère

_META_ALIASES = {
    "obs_id": ["obs_id", "id", "avis_id", "review_id", "identifiant_avis", "id_avis"],
    "operator": ["operator", "operateur", "nom_operateur", "op"],
    "source": ["source", "origine", "source_collecte"],
    "submitted_at": ["submitted_at", "date", "date_avis", "date_soumission",
                     "date_de_soumission", "created_at", "timestamp", "horodatage"],
    "visitor_id": ["visitor_id", "visitor", "visiteur", "visiteur_id", "id_visiteur",
                   "visitor_token", "session_id"],
    "batch_ref": ["batch_ref", "lot", "batch", "campagne", "campaign", "id_lot"],
    "comment": ["comment", "commentaire", "texte", "avis_texte"],
    "verified_label": ["verified_label", "label_verifie", "label"],
}

COLUMN_ALIASES: Dict[str, str] = {}
for _canon, _als in _META_ALIASES.items():
    for _a in _als:
        COLUMN_ALIASES[_a] = _canon
for _i, _k in enumerate(CRITERIA_KEYS, start=1):
    for _a in (_k, f"note_{_k}", f"critere_{_i}", f"note_{_i}", f"c{_i:02d}"):
        COLUMN_ALIASES[_a] = _k


# --------------------------------------------------------------------------
# Configuration
# --------------------------------------------------------------------------
@dataclass
class EngineConfig:
    # --- notes et seuils (configurables) ---
    rating_min: float = 0.0
    rating_max: float = 10.0
    low_threshold: float = 4.0    # note < 4  -> "basse"
    high_threshold: float = 7.0   # note >= 7 -> "haute" ; entre les deux -> "moyenne"

    # --- représentativité / périodes ---
    min_n_reliable: int = 30      # en dessous : résultat marqué "échantillon insuffisant"
    min_n_period: int = 10
    period_start: Optional[str] = None   # ISO 8601 ; None = étendue du lot (documenté)
    period_end: Optional[str] = None
    trend_freq: str = "W"

    # --- pondérations (aucune pondération arbitraire : égale par défaut) ---
    criterion_weights: Dict[str, float] = field(default_factory=dict)  # défaut 1.0
    global_weights: Dict[str, float] = field(default_factory=dict)     # défaut 1.0
    compute_global: bool = False   # score global facultatif, désactivé par défaut

    # --- prétraitement ---
    visitor_salt: str = "CHANGE-ME-IN-PRODUCTION"
    timezone: str = "Indian/Antananarivo"
    date_dayfirst: bool = False
    min_valid_date: str = "2015-01-01"
    future_tolerance_hours: int = 24
    reference_now: Optional[str] = None     # fixé dans les tests pour reproductibilité
    duplicate_window_minutes: int = 10
    extra_rules: List[Callable] = field(default_factory=list)  # callable(df)->Series[code|None]

    # --- règles d'anomalie ---
    visitor_burst_threshold: int = 5
    visitor_burst_window_minutes: int = 60
    burst_z: float = 4.0
    burst_min_count: int = 10
    burst_min_hours: int = 24
    repeated_comment_threshold: int = 3
    repeated_comment_min_len: int = 10
    source_divergence_threshold: float = 2.0

    # --- Isolation Forest ---
    min_samples_isolation_forest: int = 200
    iforest_contamination: float = 0.05
    iforest_n_estimators: int = 200
    iforest_min_score: float = 0.65   # plancher absolu heuristique : à calibrer sur données réelles
    random_state: int = 42
    use_registry_models: bool = True
    compare_detectors: bool = False

    # --- supervisé (uniquement si labels vérifiés) ---
    supervised_min_labeled: int = 200
    supervised_min_per_class: int = 30
    supervised_min_f1: float = 0.70

    include_review_in_scores: bool = True

    def to_public_dict(self) -> dict:
        return {f.name: getattr(self, f.name) for f in fields(self) if f.name != "extra_rules"}


AUTHENTICITY_STATUSES = (
    "rejected_structural",      # rejeté par la validation structurelle
    "needs_review",             # indicateur(s) à examiner par un agent
    "no_anomaly_detected",      # aucun indicateur -- NE SIGNIFIE PAS "authentique"
    "not_assessed",             # analyse impossible (erreur / données insuffisantes)
    "model_flagged_unreliable", # uniquement si un modèle supervisé qualifié existe
)
