from apps.core.services import client_ip, log_audit


class AuditMixin:
    """Logs create/update/delete operations through the audit service."""

    audit_actions = ("create", "update", "destroy")

    def perform_create(self, serializer):
        super().perform_create(serializer)
        self._audit("CREATE", serializer.instance)

    def perform_update(self, serializer):
        super().perform_update(serializer)
        self._audit("UPDATE", serializer.instance)

    def perform_destroy(self, instance):
        self._audit("DELETE", instance)
        super().perform_destroy(instance)

    def _audit(self, action: str, instance):
        log_audit(
            user=getattr(self.request, "user", None),
            action=action,
            target=instance,
            ip_address=client_ip(self.request),
        )
