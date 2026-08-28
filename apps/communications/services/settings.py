from apps.communications.models import CommunicationsSettings


def get_communications_settings() -> CommunicationsSettings:
    """Plain get_or_create -- unlike apps.systemsettings.services.get_settings
    this isn't a hot per-request read path (only send jobs and the Ajustes
    page touch it), so no caching layer is needed."""
    obj, _created = CommunicationsSettings.objects.get_or_create(pk=1)
    return obj
