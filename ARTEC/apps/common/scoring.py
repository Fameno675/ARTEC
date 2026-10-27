"""Règles de notation et de statistique, définies à un seul endroit.

Règle positif / neutre / négatif (appliquée à chaque NOTE, pas à chaque avis) :
    positif : 7 à 10   neutre : 5 à 6   négatif : 0 à 4
quality_score = moyenne des notes (calculée par `analytics`, jamais par le ML).
"""
import math

from django.conf import settings

SCALE_MIN = 0
SCALE_MAX = 10
POSITIVE_MIN = 7
NEUTRAL_MIN = 5


def sentiment(score: int) -> str:
    if score >= POSITIVE_MIN:
        return "positive"
    if score >= NEUTRAL_MIN:
        return "neutral"
    return "negative"


def min_sample() -> int:
    return settings.ARTEC_MIN_SAMPLE


def mean_ci95(n, mean, std):
    """Intervalle de confiance à 95 % (approximation normale) de la moyenne, borné à [0, 10]."""
    if not n or n < 2 or mean is None or std is None:
        return None
    half = 1.96 * float(std) / math.sqrt(n)
    return [round(max(SCALE_MIN, float(mean) - half), 2), round(min(SCALE_MAX, float(mean) + half), 2)]


LIMITATIONS = [
    "Les avis sont volontaires et ne sont pas représentatifs de l'ensemble des abonnés.",
    "Une moyenne calculée sur un petit échantillon n'est pas fiable ; les échantillons inférieurs au seuil ne sont pas classés.",
    "Les résultats reflètent la perception des répondants, pas une mesure technique du réseau.",
]
