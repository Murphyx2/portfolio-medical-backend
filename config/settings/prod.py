"""Production settings (hardened)."""

from django.core.exceptions import ImproperlyConfigured

from .base import *  # noqa: F401,F403
from .base import env

DEBUG = False

# Fail fast on insecure secrets in production.
_INSECURE_SECRETS = {
    "",
    "dev-insecure-secret-key-change-me",
    "change-me-to-a-long-random-string",
}
if not SECRET_KEY or SECRET_KEY in _INSECURE_SECRETS or len(SECRET_KEY) < 32:
    raise ImproperlyConfigured(
        "DJANGO_SECRET_KEY must be a strong random value (>= 32 chars) in "
        "production. Generate one with `python -c \"import secrets; "
        "print(secrets.token_urlsafe(64))\"`."
    )
if not ALLOWED_HOSTS:
    raise ImproperlyConfigured(
        "DJANGO_ALLOWED_HOSTS must be set to the real host(s) in production."
    )
if not env("PII_FIELD_KEY", ""):
    raise ImproperlyConfigured(
        "PII_FIELD_KEY is required in production; existing encrypted patient "
        "data cannot be read without it."
    )

# Security hardening
# SSL redirect is on by default, but the bundled compose stack has no TLS
# terminator yet; set DJANGO_SECURE_SSL_REDIRECT=false there (add TLS at a
# reverse proxy before real deployments).
SECURE_SSL_REDIRECT = env("DJANGO_SECURE_SSL_REDIRECT", "true").lower() in (
    "1",
    "true",
    "yes",
    "on",
)
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_HSTS_SECONDS = 31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
X_FRAME_OPTIONS = "DENY"

# Refresh cookie must be Secure over TLS in production (default on).
REFRESH_COOKIE_SECURE = env("DJANGO_REFRESH_COOKIE_SECURE", "true").lower() in (
    "1",
    "true",
    "yes",
    "on",
)
