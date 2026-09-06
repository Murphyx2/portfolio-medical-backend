"""Core serializer primitives shared across apps.

One base class owns the two conventions every model serializer repeated by
hand: the request->user seam and the active-field writability rule (only
admins may write ``active``; everyone else sees it read-only). Subclasses
inherit both and drop their private copies.
"""

from rest_framework import serializers

from apps.core.models import AuditLog
from apps.core.services import can_view_inactive


class CoreModelSerializer(serializers.ModelSerializer):
    """Base for every model serializer.

    Owns:
    - ``_request_user()``: the request->user seam (previously a copy-pasted
      module-level ``_request_user(context)`` in five apps).
    - ``get_fields()``: marks ``active`` read-only unless the requester may
      view inactive rows (``can_view_inactive``). Subclasses that need extra
      ``get_fields`` work call ``super().get_fields()`` first.
    """

    def _request_user(self):
        request = self.context.get("request")
        return getattr(request, "user", None) if request else None

    def get_fields(self):
        fields = super().get_fields()
        if "active" in fields and not can_view_inactive(self._request_user()):
            fields["active"].read_only = True
        return fields


class AuditLogSerializer(serializers.ModelSerializer):
    """Read-only view of a user's audit trail (see accounts UserViewSet's
    ``activity`` action)."""

    class Meta:
        model = AuditLog
        fields = ["id", "action", "target_type", "target_id", "ip_address", "details", "created_at"]
        read_only_fields = fields


def full_name_or_username(user) -> str:
    """Shared body for the ``get_created_by_name``/``get_doctor_name``
    SerializerMethodFields repeated across records/appointments/encounters
    serializers -- always masked (``masked_fields=("created_by_name",)`` or
    similarly named) wherever it appears."""
    return user.get_full_name() or user.username
