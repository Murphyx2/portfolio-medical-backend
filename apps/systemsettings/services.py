"""``get_settings()`` -- the one read path every consumer (lockout, throttles,
JWT lifetimes, password policy, upload size, media tokens, pagination)
should use instead of querying ``SystemSettings`` directly.

Caching: a Redis-backed (LocMemCache in tests) cache entry holds the live
singleton row, invalidated two ways -- a ``post_save`` signal
(``apps/systemsettings/signals.py``) for the common case, and a bounded ~60s
TTL backstop so a missed/failed invalidation self-heals instead of
persisting stale (possibly looser) security settings indefinitely (revision
changelog item, SETTINGS_PAGE_PLAN.md).

Fallback chain on failure: cache -> DB -> hardcoded defaults, matching the
existing fail-fast/degrade Redis posture used by ``apps/core/caching.py``.
"""

import logging
from types import SimpleNamespace

from django.core.cache import cache

logger = logging.getLogger(__name__)

CACHE_KEY = "systemsettings:singleton"
CACHE_TTL = 60  # seconds -- bounded staleness backstop

# Single source of truth for "which fields are user-editable settings" --
# used to build the SimpleNamespace fallback and the reset-to-defaults
# payload from the model's own field defaults, so this list and the model
# can't silently drift apart.
EDITABLE_FIELDS = [
    "login_lockout_threshold",
    "login_lockout_minutes",
    "password_min_length",
    "access_token_lifetime_minutes",
    "refresh_token_lifetime_days",
    "login_rate_limit_per_min",
    "anon_rate_limit_per_min",
    "user_rate_limit_per_min",
    "max_image_upload_mb",
    "media_token_ttl_minutes",
    "default_page_size",
]


def default_values() -> dict:
    """The section-2 defaults, read from the model's field definitions
    (not hand-duplicated) -- used both by the hardcoded-fallback path here
    and by the reset-to-defaults API action."""
    from apps.systemsettings.models import SystemSettings

    return {
        name: SystemSettings._meta.get_field(name).default for name in EDITABLE_FIELDS
    }


def get_settings():
    """Returns an object exposing every field in ``EDITABLE_FIELDS`` as an
    attribute: either the live (cached) ``SystemSettings`` row, or --  if
    the cache is empty and the DB read itself fails -- a ``SimpleNamespace``
    of hardcoded defaults, so callers never need a try/except of their own.
    """
    cached = cache.get(CACHE_KEY)
    if cached is not None:
        return cached

    from apps.systemsettings.models import SystemSettings

    try:
        obj = SystemSettings.objects.first()
        if obj is None:
            obj = SystemSettings.objects.create(pk=1)
    except Exception:
        logger.exception(
            "Failed to load SystemSettings from the database; falling back "
            "to hardcoded defaults."
        )
        return SimpleNamespace(**default_values())

    cache.set(CACHE_KEY, obj, timeout=CACHE_TTL)
    return obj


def invalidate_settings_cache() -> None:
    cache.delete(CACHE_KEY)
