from rest_framework.decorators import action
from rest_framework.response import Response

from apps.core.services import (
    can_view_inactive,
    client_ip,
    deactivate_with_cascade,
    log_audit,
    soft_delete_field_name,
)


class AuditMixin:
    """Logs create/update/delete operations through the audit service, and
    (for soft-deletable models) filters inactive rows out of get_queryset()
    by default, deactivates instead of hard-deleting, and exposes a restore
    action -- all gated by the single can_view_inactive() check, so this
    reaches every ViewSet that includes this mixin for free.
    """

    audit_actions = ("create", "update", "destroy", "restore")

    def get_queryset(self):
        qs = super().get_queryset()
        field = soft_delete_field_name(qs.model)
        if field:
            # The restore action inherently targets an inactive row, so it
            # always widens for anyone who reaches it (restore() itself is
            # already gated to admins before get_object()) -- without this,
            # get_object() inside restore() could never find the row it's
            # meant to restore, since a plain POST .../restore/ never carries
            # ?include_inactive=true itself.
            include_inactive = can_view_inactive(
                getattr(self.request, "user", None)
            ) and (
                getattr(self, "action", None) == "restore"
                or self.request.query_params.get("include_inactive", "").lower() == "true"
            )
            if not include_inactive:
                qs = qs.filter(**{field: True})
        return qs

    def perform_create(self, serializer):
        super().perform_create(serializer)
        self._audit("CREATE", serializer.instance)

    def perform_update(self, serializer):
        super().perform_update(serializer)
        self._audit("UPDATE", serializer.instance)

    def perform_destroy(self, instance):
        self._audit("DELETE", instance)
        field = soft_delete_field_name(type(instance))
        if field is None:
            super().perform_destroy(instance)
        else:
            deactivate_with_cascade(instance)

    @action(detail=True, methods=["post"])
    def restore(self, request, pk=None):
        # Restore is admin-only (invariant #7). It can't rely on the action
        # decorator's permission_classes: every ViewSet's get_permissions()
        # override replaces them for non-SAFE methods (restore is a POST), so
        # a role that can write this resource would otherwise be able to
        # restore deactivated rows. Enforce it inside the action, before
        # get_object(), so a non-admin 403s without confirming the row exists.
        if not can_view_inactive(request.user):
            self.permission_denied(request, message="Restore is admin-only.")
        instance = self.get_object()
        field = soft_delete_field_name(type(instance))
        if field is None:
            return Response(
                {"detail": "This resource does not support restore."}, status=400
            )
        setattr(instance, field, True)
        instance.save(update_fields=[field])
        self._audit("UPDATE", instance)
        return Response(self.get_serializer(instance).data)

    def _audit(self, action: str, instance):
        log_audit(
            user=getattr(self.request, "user", None),
            action=action,
            target=instance,
            ip_address=client_ip(self.request),
        )
