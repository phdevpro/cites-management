import os
from pathlib import Path
from urllib.parse import urlparse

BASE_DIR = Path(__file__).resolve().parent.parent


def _load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


_load_dotenv(BASE_DIR / ".env")

DEBUG = os.environ.get("DJANGO_DEBUG", "1") == "1"
SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "")
if not SECRET_KEY:
    if not DEBUG:
        raise RuntimeError("DJANGO_SECRET_KEY must be set when DJANGO_DEBUG=0")
    SECRET_KEY = "dev-insecure-key-change-me"
ALLOWED_HOSTS = [h for h in os.environ.get("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1").split(",") if h]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.humanize",
    "simple_history",
    "apps.vault",
    "apps.accounts",
    "apps.species",
    "apps.registry",
    "apps.declarations",
    "apps.pdfforms",
    "apps.importer",
    "apps.dashboard",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "config.security.AdminIPAllowlistMiddleware",
    "config.security.PermissionsPolicyMiddleware",
    "csp.middleware.CSPMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.locale.LocaleMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "simple_history.middleware.HistoryRequestMiddleware",
    "apps.vault.middleware.VaultActivateMiddleware",
    "apps.accounts.middleware.CurrentKeeperMiddleware",
    "apps.accounts.middleware.TermsAcceptanceMiddleware",
    "apps.vault.middleware.VaultGateMiddleware",
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
                "apps.accounts.context_processors.keeper",
                "apps.accounts.context_processors.legal",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"


def _database_from_url(url: str) -> dict:
    if not url:
        return {"ENGINE": "django.db.backends.sqlite3", "NAME": BASE_DIR / "db.sqlite3"}
    parsed = urlparse(url)
    if parsed.scheme.startswith("postgres"):
        return {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": parsed.path.lstrip("/"),
            "USER": parsed.username or "",
            "PASSWORD": parsed.password or "",
            "HOST": parsed.hostname or "",
            "PORT": parsed.port or "",
        }
    if parsed.scheme == "sqlite":
        return {"ENGINE": "django.db.backends.sqlite3", "NAME": parsed.path}
    raise ValueError(f"Unsupported DATABASE_URL scheme: {parsed.scheme}")


DATABASES = {"default": _database_from_url(os.environ.get("DATABASE_URL", ""))}
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
]

LANGUAGE_CODE = "it"
LANGUAGES = [("it", "Italiano"), ("en", "English")]
TIME_ZONE = "Europe/Rome"
USE_I18N = True
USE_TZ = True
LOCALE_PATHS = [BASE_DIR / "locale"]

STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = Path(os.environ.get("STATIC_ROOT", BASE_DIR / "staticfiles"))
STORAGES = {
    # uploads are encrypted with the owning keeper's key and stored under random names
    "default": {"BACKEND": "apps.vault.storage.EncryptedFileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage" if not DEBUG
                    else "django.contrib.staticfiles.storage.StaticFilesStorage"},
}

MEDIA_URL = "/media/"
MEDIA_ROOT = Path(os.environ.get("MEDIA_ROOT", BASE_DIR / "media"))

LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "dashboard:home"
LOGOUT_REDIRECT_URL = "login"

EMAIL_BACKEND = (
    "django.core.mail.backends.smtp.EmailBackend"
    if os.environ.get("EMAIL_HOST")
    else "django.core.mail.backends.console.EmailBackend"
)
EMAIL_HOST = os.environ.get("EMAIL_HOST", "")
EMAIL_PORT = int(os.environ.get("EMAIL_PORT", "587"))
EMAIL_HOST_USER = os.environ.get("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = os.environ.get("EMAIL_HOST_PASSWORD", "")
EMAIL_USE_TLS = True
DEFAULT_FROM_EMAIL = os.environ.get("DEFAULT_FROM_EMAIL", "cites@localhost")

SPECIESPLUS_TOKEN = os.environ.get("SPECIESPLUS_TOKEN", "")

# Upload limits: scanned PDFs in the archive reach ~11 MB
DATA_UPLOAD_MAX_MEMORY_SIZE = 50 * 1024 * 1024
FILE_UPLOAD_MAX_MEMORY_SIZE = 10 * 1024 * 1024

# Deadlines (days) — configurable, verify with the local Nucleo CITES
CITES_DEADLINES = {
    "birth": 10,  # art. 8-bis L. 150/92
    "marking_details": 45,  # SCT1 footnote 2
    "testudo_microchip": 365,  # SCT1 footnote: within first year of life
    "death": 10,  # no fixed legal term; customary
    "register_entry": 15,  # D.M. 8/1/2002 registro carico/scarico
    "annex_a_listing": 90,  # art. 5-bis c.4 denuncia di detenzione
}

# PDF previews are embedded in same-origin iframes
X_FRAME_OPTIONS = "SAMEORIGIN"

CSRF_TRUSTED_ORIGINS = [o for o in os.environ.get("DJANGO_CSRF_TRUSTED_ORIGINS", "").split(",") if o]
if not DEBUG:
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SESSION_COOKIE_SECURE = os.environ.get("DJANGO_SECURE_COOKIES", "1") == "1"
    CSRF_COOKIE_SECURE = SESSION_COOKIE_SECURE
    SECURE_CONTENT_TYPE_NOSNIFF = True

# Encryption: scrypt cost for passphrases (2**15 ≈ 32 MB, ~0.1 s) and unlock lifetime
VAULT_SCRYPT_N = int(os.environ.get("VAULT_SCRYPT_N", 2 ** 15))
VAULT_UNLOCK_MAX_AGE = int(os.environ.get("VAULT_UNLOCK_MAX_AGE", 12 * 3600))

# Who runs this instance (a private person: personal, non-commercial open-source project).
# Set in the environment; the repo is public.
LEGAL = {
    "name": os.environ.get("LEGAL_NAME", ""),
    "email": os.environ.get("LEGAL_EMAIL", ""),
    "source_url": os.environ.get("SOURCE_URL", "https://github.com/phdevpro/cites-management"),
    "forum": os.environ.get("LEGAL_FORUM", ""),  # e.g. "Milano"
    "updated": os.environ.get("LEGAL_UPDATED", "2026-10-18"),  # bump to require re-acceptance
    "clauses": "4, 5, 6, 9, 10, 11, 12, 15",
}
SITE_NAME = os.environ.get("SITE_NAME", "CITES Manager")

# Import analysis (OCR) runs in a background thread so uploads return immediately
IMPORT_BACKGROUND = os.environ.get("IMPORT_BACKGROUND", "1") == "1"

# AI reading of imported documents via Regolo.ai (OpenAI-compatible, EU). Disabled without a key.
REGOLO_API_KEY = os.environ.get("REGOLO_API_KEY", "")
REGOLO_BASE_URL = os.environ.get("REGOLO_BASE_URL", "https://api.regolo.ai/v1")
AI_OCR_MODEL = os.environ.get("AI_OCR_MODEL", "deepseek-ocr-2")
AI_EXTRACT_MODEL = os.environ.get("AI_EXTRACT_MODEL", "qwen3.5-122b")
AI_MAX_PAGES = int(os.environ.get("AI_MAX_PAGES", 30))
AI_MIN_CONFIDENCE = float(os.environ.get("AI_MIN_CONFIDENCE", 0.75))  # below: ask the user

# --- Hardening ---------------------------------------------------------------
# Admin lives at a configurable path and, when ADMIN_ALLOWED_IPS is set (comma-separated IPs/CIDRs),
# answers 404 to everyone else. TRUSTED_PROXY_COUNT = proxies in front of the app that append to
# X-Forwarded-For (1 = Traefik only, 2 = Cloudflare proxy + Traefik).
ADMIN_URL = os.environ.get("ADMIN_URL", "admin/").strip("/") + "/"
ADMIN_ALLOWED_IPS = [n for n in os.environ.get("ADMIN_ALLOWED_IPS", "").split(",") if n.strip()]
TRUSTED_PROXY_COUNT = int(os.environ.get("TRUSTED_PROXY_COUNT", "0" if DEBUG else "1"))

# Self-registration (set ALLOW_SIGNUP=0 for a private instance) and Cloudflare Turnstile on signup
ALLOW_SIGNUP = os.environ.get("ALLOW_SIGNUP", "1") == "1"
TURNSTILE_SITE_KEY = os.environ.get("TURNSTILE_SITE_KEY", "")
TURNSTILE_SECRET_KEY = os.environ.get("TURNSTILE_SECRET_KEY", "")

# Content-Security-Policy: no inline scripts anywhere (behaviour lives in static/app.js).
# Inline style attributes are still used by templates, hence 'unsafe-inline' for styles only.
_TURNSTILE = ["https://challenges.cloudflare.com"] if TURNSTILE_SITE_KEY else []
_CSP = {
    "DIRECTIVES": {
        "default-src": ["'self'"],
        "script-src": ["'self'", *_TURNSTILE],
        "style-src": ["'self'", "'unsafe-inline'"],
        "img-src": ["'self'", "data:", "blob:"],
        "font-src": ["'self'"],
        "connect-src": ["'self'"],
        "frame-src": ["'self'", *_TURNSTILE],
        "object-src": ["'none'"],
        "base-uri": ["'self'"],
        "form-action": ["'self'"],
        "frame-ancestors": ["'self'"],
    }
}
if os.environ.get("CSP_REPORT_ONLY", "0") == "1":
    CONTENT_SECURITY_POLICY_REPORT_ONLY = _CSP
else:
    CONTENT_SECURITY_POLICY = _CSP

SECURE_REFERRER_POLICY = "same-origin"
SECURE_CROSS_ORIGIN_OPENER_POLICY = "same-origin"
SECURITY_CONTACT = os.environ.get("SECURITY_CONTACT", "")  # mailto:… or https://…; defaults to LEGAL_EMAIL
