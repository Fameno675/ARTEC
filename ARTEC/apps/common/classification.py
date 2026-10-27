"""Classement d'un avis : accepté ou à examiner (le rejet relève de la validation de structure)."""
from datetime import date, timedelta

from .utils import contains_url

REVIEW_OLD_DAYS = 730  # 2 ans


def review_reasons(scores: dict, comment: str, collected_at: date, *, check_straight_lining=True, today=None):
    today = today or date.today()
    reasons = []
    values = [v for v in scores.values() if v is not None]
    if check_straight_lining and len(values) >= 3 and len(set(values)) == 1 and values[0] in (0, 10):
        reasons.append("all_scores_identical_extreme")
    if collected_at < today - timedelta(days=REVIEW_OLD_DAYS):
        reasons.append("date_older_than_2_years")
    if comment and contains_url(comment):
        reasons.append("comment_contains_url")
    return reasons
