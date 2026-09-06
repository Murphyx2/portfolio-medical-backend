from rest_framework import status
from rest_framework.generics import RetrieveUpdateAPIView
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response

from apps.core.permissions import IsAdmin, IsAdminOrITReadOnly
from apps.core.services import client_ip, log_audit
from apps.systemsettings.models import SystemSettings
from apps.systemsettings.serializers import SystemSettingsSerializer
from apps.systemsettings.services import default_values, invalidate_settings_cache


def _get_singleton() -> SystemSettings:
    obj, _created = SystemSettings.objects.get_or_create(pk=1)
    return obj


class SystemSettingsView(RetrieveUpdateAPIView):
    """``GET/PATCH /api/settings/`` -- retrieve + partial_update only (no
    create/delete: the singleton row always exists). ADMIN gets full
    read/write; IT is read-only; every other role is denied
    (``IsAdminOrITReadOnly``)."""

    permission_classes = [IsAdminOrITReadOnly]
    serializer_class = SystemSettingsSerializer
    http_method_names = ["get", "patch", "head", "options"]

    def get_object(self):
        return _get_singleton()

    def perform_update(self, serializer):
        instance = serializer.instance
        before = {
            field: getattr(instance, field) for field in serializer.validated_data
        }
        serializer.save(updated_by=self.request.user)
        changed_fields = sorted(
            field
            for field, old_value in before.items()
            if old_value != getattr(serializer.instance, field)
        )
        log_audit(
            user=self.request.user,
            action="UPDATE",
            target=serializer.instance,
            ip_address=client_ip(self.request),
            details={"changed_fields": changed_fields} if changed_fields else None,
        )


@api_view(["POST"])
@permission_classes([IsAdmin])
def reset_settings(request):
    """``POST /api/settings/reset/`` (ADMIN-only) -- resets every field to
    the section-2 defaults, so an admin can recover from a bad value (e.g.
    an overly aggressive lockout) without DB/shell access. Logs a distinct
    ``action="SETTINGS_RESET"`` audit entry, separate from the normal PATCH
    diff, so it's identifiable in the activity trail."""

    instance = _get_singleton()
    defaults = default_values()
    for field, value in defaults.items():
        setattr(instance, field, value)
    instance.updated_by = request.user
    instance.save()
    invalidate_settings_cache()
    log_audit(
        user=request.user,
        action="SETTINGS_RESET",
        target=instance,
        ip_address=client_ip(request),
    )
    return Response(
        SystemSettingsSerializer(instance).data, status=status.HTTP_200_OK
    )
