"""Test settings: fast, isolated SQLite in-memory DB and fixed test key."""

from cryptography.fernet import Fernet

from .dev import *  # noqa: F401,F403

# Fast in-memory tests, independent of PostgreSQL/Redis in the host.
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": ":memory:",
    }
}

PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]

# Ephemeral Fernet key generated per test run — never commit a real key.
PII_FIELD_KEY = Fernet.generate_key().decode()

CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
    }
}

# Never hit real SMTP during tests (apps.communications).
EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
