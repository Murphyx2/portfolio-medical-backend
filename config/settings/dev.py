"""Development settings."""

from .base import *  # noqa: F401,F403
from .base import BASE_DIR, env_bool

DEBUG = True

# Optional: run without PostgreSQL for quick local checks / tests.
if env_bool("USE_SQLITE", "false"):
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
        }
    }
