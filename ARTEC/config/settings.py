"""Configuration ARTEC. Les secrets viennent exclusivement de l'environnement (.env)."""
import os
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


def env_bool(name, default=False):
    return os.environ.get(name, str(default)).strip().lower() in ("1", "true", "yes", "on")


def env_int(name, default):
    return int(os.environ.get(name, default))


DEBUG = env_bool("DJANGO_DEBUG", False)

SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "")
if not SECRET_KEY:
    if DEBUG:
        SECRET_KEY = "dev-only-insecure-key-do-not-use-in-production"
    else:
        raise ImproperlyConfigured("DJANGO_SECRET_KEY doit être défini dans l'environnement (.env).")

ALLOWED_HOSTS = [h.strip() for h in os.environ.get("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1").split(",") if h.strip()]
CSRF_TRUSTED_ORIGINS = [o.strip() for o in os.environ.get("DJANGO_CSRF_TRUSTED_ORIGINS", "").split(",") if o.strip()]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "apps.common",
    "apps.audit",
    "apps.operators",
    "apps.accounts",
    "apps.feedback",
    "apps.datasets",
    "apps.complaints",
    "apps.analytics",
    "apps.dashboard",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "apps.accounts.middleware.ForcePasswordChangeMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.environ.get("DB_NAME", "artec"),
        "USER": os.environ.get("DB_USER", "artec"),
        "PASSWORD": os.environ.get("DB_PASSWORD", ""),
        "HOST": os.environ.get("DB_HOST", "localhost"),
        "PORT": os.environ.get("DB_PORT", "5432"),
        "CONN_MAX_AGE": 60,
    }
}

AUTH_USER_MODEL = "accounts.User"
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 10}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]
PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.PBKDF2PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2SHA1PasswordHasher",
]

LOGIN_URL = "accounts:login"
LOGIN_REDIRECT_URL = "accounts:home_redirect"
LOGOUT_REDIRECT_URL = "public:home"

LANGUAGE_CODE = "fr"
TIME_ZONE = "Indian/Antananarivo"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"] if (BASE_DIR / "static").exists() else []
STATIC_ROOT = BASE_DIR / "staticfiles"

# Fichiers privés : jamais servis directement, jamais dans Git.
PRIVATE_MEDIA_ROOT = Path(os.environ.get("PRIVATE_MEDIA_ROOT", BASE_DIR / "private_media"))

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

SESSION_COOKIE_AGE = 60 * 60 * 8
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SAMESITE = "Lax"
X_FRAME_OPTIONS = "DENY"
SECURE_CONTENT_TYPE_NOSNIFF = True

if not DEBUG:
    SESSION_COOKIE_SECURE = env_bool("DJANGO_SECURE_COOKIES", True)
    CSRF_COOKIE_SECURE = env_bool("DJANGO_SECURE_COOKIES", True)
    SECURE_SSL_REDIRECT = env_bool("DJANGO_SSL_REDIRECT", True)
    SECURE_HSTS_SECONDS = env_int("DJANGO_HSTS_SECONDS", 3600)

# --- Paramètres métier ARTEC -------------------------------------------------
ARTEC_MIN_SAMPLE = env_int("ARTEC_MIN_SAMPLE", 30)

IMPORT_MAX_FILE_BYTES = env_int("IMPORT_MAX_FILE_BYTES", 10 * 1024 * 1024)
IMPORT_MAX_ROWS = env_int("IMPORT_MAX_ROWS", 50_000)
IMPORT_MAX_REJECT_RATE = float(os.environ.get("IMPORT_MAX_REJECT_RATE", "0.20"))

COMPLAINT_MAX_ATTACHMENT_BYTES = env_int("COMPLAINT_MAX_ATTACHMENT_BYTES", 10 * 1024 * 1024)

FEEDBACK_MIN_FILL_SECONDS = env_int("FEEDBACK_MIN_FILL_SECONDS", 5)
FEEDBACK_DEVICE_WINDOW_HOURS = env_int("FEEDBACK_DEVICE_WINDOW_HOURS", 24)
FEEDBACK_NETWORK_REVIEW_PER_HOUR = env_int("FEEDBACK_NETWORK_REVIEW_PER_HOUR", 20)
FEEDBACK_NETWORK_BLOCK_PER_HOUR = env_int("FEEDBACK_NETWORK_BLOCK_PER_HOUR", 100)
FEEDBACK_CLIENT_HASH_RETENTION_DAYS = 30
# À activer seulement derrière un reverse proxy de confiance.
TRUST_X_FORWARDED_FOR = env_bool("TRUST_X_FORWARDED_FOR", False)

LOGIN_MAX_FAILURES = env_int("LOGIN_MAX_FAILURES", 5)
LOGIN_LOCKOUT_SECONDS = env_int("LOGIN_LOCKOUT_SECONDS", 900)

# "local" : appel Python à ml_engine ; "unavailable" : moteur désactivé.
ML_ENGINE_BACKEND = os.environ.get("ML_ENGINE_BACKEND", "local")
ML_MIN_OBSERVATIONS_FOR_MODEL = env_int("ML_MIN_OBSERVATIONS_FOR_MODEL", 50)
# Sel du pseudonymat côté moteur ML : dérivé de la clé secrète si non fourni (jamais de valeur par défaut publique).
import hashlib as _hashlib
ML_VISITOR_SALT = os.environ.get("ML_VISITOR_SALT") or _hashlib.sha256(f"artec-ml:{SECRET_KEY}".encode()).hexdigest()
