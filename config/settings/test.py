"""Test settings: fast, isolated SQLite in-memory DB and fixed test key."""

from .dev import *  # noqa: F401,F403

# Fast in-memory tests, independent of PostgreSQL/Redis in the host.
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": ":memory:",
    }
}

PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]

PII_FIELD_KEY = "alyI0fnDeRnpQBbZBGSruo6djlfn4J5XW0I-_mNiCA0="

CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
    }
}
