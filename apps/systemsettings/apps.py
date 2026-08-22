from django.apps import AppConfig


class SystemsettingsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.systemsettings"

    def ready(self):
        from apps.systemsettings.signals import connect_cache_invalidation

        connect_cache_invalidation()
