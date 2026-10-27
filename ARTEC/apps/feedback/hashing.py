from apps.common.utils import sha256_text


def content_hash(operator_code: str, collected_at, scores: dict, source: str) -> str:
    """SHA-256 de (opérateur, date, notes triées, source)."""
    notes = ",".join(f"{k}={v}" for k, v in sorted(scores.items()) if v is not None)
    return sha256_text(f"{operator_code}|{collected_at.isoformat()}|{notes}|{source}")


def external_key_hash(operator_code: str, source: str, external_id: str) -> str:
    return sha256_text(f"ext|{operator_code}|{source}|{external_id}")
