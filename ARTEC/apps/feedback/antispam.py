"""Anti-spam sans compte ni donnée personnelle brute.

- cookie d'appareil signé -> device_hash (HMAC) ; si le cookie manque, aucune limite d'appareil
  n'est appliquée (on ne pénalise pas les connexions partagées) ;
- network hash = HMAC(sel du jour + IP + User-Agent) ; sert aux seuils horaires (revue / blocage) ;
- honeypot et temps de remplissage minimal.
"""
import time
import uuid
from datetime import timedelta

from django.conf import settings
from django.core import signing
from django.utils import timezone

from apps.common.utils import hmac_hex

DEVICE_COOKIE = "artec_device"
TS_SALT = "artec-form-ts"
COOKIE_MAX_AGE = settings.FEEDBACK_CLIENT_HASH_RETENTION_DAYS * 86400


def client_ip(request):
    if settings.TRUST_X_FORWARDED_FOR:
        xff = request.META.get("HTTP_X_FORWARDED_FOR", "")
        if xff:
            return xff.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR", "")


def network_hash(request):
    day = timezone.localdate().isoformat()
    ua = request.META.get("HTTP_USER_AGENT", "")[:300]
    return hmac_hex(f"net|{day}|{client_ip(request)}|{ua}")


def existing_device_id(request):
    return request.get_signed_cookie(DEVICE_COOKIE, default=None, max_age=COOKIE_MAX_AGE)


def device_hash_for(device_id):
    return hmac_hex(f"device|{device_id}") if device_id else ""


def set_device_cookie(response, device_id):
    response.set_signed_cookie(
        DEVICE_COOKIE, device_id, max_age=COOKIE_MAX_AGE, httponly=True, samesite="Lax", secure=not settings.DEBUG
    )


def new_device_id():
    return uuid.uuid4().hex


def make_form_token():
    return signing.dumps(time.time(), salt=TS_SALT)


def check_form_token(token):
    """Retourne (ok, code). code : invalid | too_fast | None."""
    try:
        issued = signing.loads(token or "", salt=TS_SALT, max_age=2 * 3600)
    except signing.BadSignature:
        return False, "invalid"
    if time.time() - float(issued) < settings.FEEDBACK_MIN_FILL_SECONDS:
        return False, "too_fast"
    return True, None


def recent_count(qs, field, value, *, hours):
    if not value:
        return 0
    since = timezone.now() - timedelta(hours=hours)
    return qs.filter(**{field: value, "submitted_at__gte": since}).count()
