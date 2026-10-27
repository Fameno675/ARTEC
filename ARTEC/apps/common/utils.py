import hashlib
import hmac
import re

from django.conf import settings

_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_URL = re.compile(r"(https?://|www\.)", re.I)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def hmac_hex(message: str) -> str:
    return hmac.new(settings.SECRET_KEY.encode(), message.encode(), hashlib.sha256).hexdigest()


def clean_text(value) -> str:
    """Texte sans caractères de contrôle, espaces normalisés en bordure."""
    return _CONTROL.sub("", str(value if value is not None else "")).strip()


def contains_url(text: str) -> bool:
    return bool(_URL.search(text or ""))


def neutralize_cell(value):
    """Protège contre l'injection de formules à l'ouverture d'un CSV dans Excel."""
    text = "" if value is None else str(value)
    if text and text[0] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + text
    return text
