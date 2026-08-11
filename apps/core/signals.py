"""Post-save / post-delete cache invalidation for the reference-data models."""

from apps.core.caching import invalidate_for_instance


def connect_cache_invalidation() -> None:
    """Wire cache-busting signals for the cached reference models.

    Called from ``CoreConfig.ready()`` so the models are guaranteed to be
    registered before the receivers are connected.
    """
    from django.db.models.signals import post_delete, post_save

    from apps.ars.models import ARS, ARSProgram
    from apps.centers.models import DoctorCenterBinding, MedicalCenter
    from apps.medicines.models import Medicine

    def _invalidate(sender, instance, **kwargs):
        invalidate_for_instance(instance)

    for model in (Medicine, ARS, ARSProgram, MedicalCenter, DoctorCenterBinding):
        post_save.connect(_invalidate, sender=model, weak=False)
        post_delete.connect(_invalidate, sender=model, weak=False)
