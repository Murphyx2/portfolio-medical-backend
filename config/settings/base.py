"""Base settings shared by all environments."""

import os
from datetime import timedelta
from pathlib import Path

from dotenv import load_dotenv

# Project root: backend/
BASE_DIR = Path(__file__).resolve().parent.parent.parent

# Load optional local .env (inside Docker the env is injected by compose).
load_dotenv(BASE_DIR / ".env")


def env(key: str, default: str | None = None) -> str | None:
    return os.getenv(key, default)


def env_bool(key: str, default: str = "false") -> bool:
    return env(key, default).lower() in ("1", "true", "yes", "on")


# ------------------------------------------------------------------
# Core Django
# ------------------------------------------------------------------
SECRET_KEY = env("DJANGO_SECRET_KEY", "dev-insecure-secret-key-change-me")
DEBUG = env_bool("DJANGO_DEBUG", "true")
ALLOWED_HOSTS = [
    h.strip()
    for h in env("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1,backend").split(",")
    if h.strip()
]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # Third-party
    "rest_framework",
    "rest_framework_simplejwt",
    "rest_framework_simplejwt.token_blacklist",
    "corsheaders",
    "django_filters",
    "drf_spectacular",
    # Local apps
    "apps.core",
    "apps.accounts",
    "apps.centers",
    "apps.ars",
    "apps.doctors",
    "apps.patients",
    "apps.records",
    "apps.medicines",
    "apps.appointments",
    "apps.services",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.middleware.gzip.GZipMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "apps.core.middleware.NoStoreMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
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
ASGI_APPLICATION = "config.asgi.application"

AUTH_USER_MODEL = "accounts.User"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# ------------------------------------------------------------------
# Database & cache
# ------------------------------------------------------------------
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": env("POSTGRES_DB", "medicalconsultations"),
        "USER": env("POSTGRES_USER", "mc_admin"),
        "PASSWORD": env("POSTGRES_PASSWORD", ""),
        "HOST": env("POSTGRES_HOST", "db"),
        "PORT": env("POSTGRES_PORT", "5432"),
        # Keep persistent connections alive between requests: saves the TCP +
        # auth handshake on every list/detail call (5-min max idle).
        "CONN_MAX_AGE": 60,
    }
}

CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.redis.RedisCache",
        "LOCATION": env("REDIS_URL", "redis://localhost:6379/0"),
        # Namespace keys (allows several apps/environments to share one Redis).
        "KEY_PREFIX": env("DJANGO_CACHE_KEY_PREFIX", "mc"),
        # A stuck/absent Redis must not block API requests: fail fast and let
        # throttling/caching degrade gracefully instead of hanging.
        "OPTIONS": {
            "socket_connect_timeout": 1,
            "socket_timeout": 1,
        },
    }
}

# ------------------------------------------------------------------
# Django REST Framework + JWT
# ------------------------------------------------------------------
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": (
        "rest_framework_simplejwt.authentication.JWTAuthentication",
    ),
    "DEFAULT_PERMISSION_CLASSES": (
        "rest_framework.permissions.IsAuthenticated",
    ),
    "DEFAULT_FILTER_BACKENDS": ("django_filters.rest_framework.DjangoFilterBackend",),
    "DEFAULT_PAGINATION_CLASS": "apps.core.pagination.DefaultPagination",
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "PAGE_SIZE": 20,
    "DEFAULT_THROTTLE_CLASSES": (
        "rest_framework.throttling.AnonRateThrottle",
        "rest_framework.throttling.UserRateThrottle",
    ),
    "DEFAULT_THROTTLE_RATES": {
        "anon": "60/min",
        "user": "300/min",
        "login": "10/min",
    },
}

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(
        minutes=int(env("JWT_ACCESS_LIFETIME_MINUTES", "15"))
    ),
    "REFRESH_TOKEN_LIFETIME": timedelta(
        days=int(env("JWT_REFRESH_LIFETIME_DAYS", "3"))
    ),
    "ROTATE_REFRESH_TOKENS": True,
    "BLACKLIST_AFTER_ROTATION": True,
}

# ------------------------------------------------------------------
# Refresh-token cookie (H-03): keep the refresh token out of JS-accessible
# storage. The SPA holds only the short-lived access token in memory; the
# refresh token travels in this httpOnly SameSite=Strict cookie, scoped to the
# auth endpoints, and is rotated on every use.
# ------------------------------------------------------------------
REFRESH_COOKIE_NAME = env("DJANGO_REFRESH_COOKIE_NAME", "mc_refresh")
REFRESH_COOKIE_MAX_AGE = int(
    timedelta(days=int(env("JWT_REFRESH_LIFETIME_DAYS", "3"))).total_seconds()
)
REFRESH_COOKIE_SECURE = env_bool("DJANGO_REFRESH_COOKIE_SECURE", "false")
REFRESH_COOKIE_SAMESITE = "Strict"
REFRESH_COOKIE_PATH = "/api/auth/"

# ------------------------------------------------------------------
# CORS
# ------------------------------------------------------------------
CORS_ALLOWED_ORIGINS = [
    o.strip()
    for o in env("DJANGO_CORS_ALLOWED_ORIGINS", "http://localhost:5173").split(",")
    if o.strip()
]
# The SPA (localhost:5173) sends/receives the refresh cookie across origin,
# so credentialed CORS is required. SameSite=Strict still protects the cookie
# against cross-site (CSRF) requests.
CORS_ALLOW_CREDENTIALS = env_bool("DJANGO_CORS_ALLOW_CREDENTIALS", "true")

# ------------------------------------------------------------------
# i18n / static / media
# ------------------------------------------------------------------
LANGUAGE_CODE = "es"
TIME_ZONE = env("TZ", "UTC")
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Fernet key used for field-level PII encryption (see apps/core/encryption.py).
PII_FIELD_KEY = env("PII_FIELD_KEY", "")

# ------------------------------------------------------------------
# OpenAPI / Swagger (drf-spectacular)
# ------------------------------------------------------------------
SPECTACULAR_SETTINGS = {
    "TITLE": "MedicalConsultations API",
    "DESCRIPTION": "Role-based medical consultations management system.",
    "VERSION": "1.0.0",
    "SERVE_INCLUDE_SCHEMA": False,
    # API docs are sensitive reconnaissance material: admins/IT only.
    "SERVE_PERMISSIONS": ["apps.core.permissions.IsAdminOrIT"],
    "COMPONENT_SPLIT_REQUEST": True,
}

# Root urls for the API.
API_URL_PREFIX = env("DJANGO_API_PREFIX", "api")
