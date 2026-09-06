"""Post-save / post-delete cache invalidation for the reference-data models."""

from apps.core.caching import _CACHE_INVALIDATION_MAP, invalidate_for_instance


def connect_cache_invalidation() -> None:
    """Wire cache-busting signals for the cached reference models.

    Called from ``CoreConfig.ready()`` so the models are guaranteed to be
    registered before the receivers are connected.

    The set of models to connect is derived from
    ``_CACHE_INVALIDATION_MAP``'s keys instead of being a separately
    hand-maintained tuple, so the map (single source of truth for "which
    model invalidates which cached lists") can't drift out of sync with
    "which models actually fire the invalidation signal". A map key with no
    matching model raises ``ImproperlyConfigured`` at startup rather than
    silently leaving that model's writes un-invalidated.
    """
    from django.core.exceptions import ImproperlyConfigured
    from django.db.models.signals import post_delete, post_save

    from apps.centers.models import DoctorCenterBinding, MedicalCenter
    from apps.medicines.models import Medicine
    from apps.records.models import APCategory, APType
    from apps.rooms.models import Room, RoomType
    from apps.services.models import Service, ServiceType

    registry = {
        model._meta.model_name: model
        for model in (
            Medicine,
            MedicalCenter,
            DoctorCenterBinding,
            Service,
            ServiceType,
            Room,
            RoomType,
            APCategory,
            APType,
        )
    }

    def _invalidate(sender, instance, **kwargs):
        invalidate_for_instance(instance)

    for name in _CACHE_INVALIDATION_MAP:
        model = registry.get(name)
        if model is None:
            raise ImproperlyConfigured(
                f"apps.core.caching._CACHE_INVALIDATION_MAP has key "
                f"'{name}' with no matching model registered in "
                f"apps.core.signals.connect_cache_invalidation()."
            )
        post_save.connect(_invalidate, sender=model, weak=False)
        post_delete.connect(_invalidate, sender=model, weak=False)
