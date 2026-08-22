"""Post-save cache invalidation for the SystemSettings singleton -- wired
from ``SystemsettingsConfig.ready()``, mirroring the
``apps/core/signals.py``/``apps/core/caching.py`` convention used for the
reference-data caches, but a single fixed key (no version-map) since there
is only ever one row."""

from django.db.models.signals import post_save

from apps.systemsettings.services import invalidate_settings_cache


def connect_cache_invalidation() -> None:
    from apps.systemsettings.models import SystemSettings

    def _invalidate(sender, instance, **kwargs):
        invalidate_settings_cache()

    post_save.connect(_invalidate, sender=SystemSettings, weak=False)
