from django.contrib import admin

from apps.core.models import AuditLog
from apps.core.services import client_ip, deactivate_with_cascade, log_audit


class AuditModelAdmin(admin.ModelAdmin):
    """ModelAdmin base mirroring the DRF ``AuditMixin`` (M-07): every add,
    change, or delete made through Django admin is written to the app's
    AuditLog, so admin edits no longer bypass the audit trail.

    Also mirrors the DRF soft-delete behavior: deactivated rows stay visible
    here (get_queryset), single-object deletion deactivates+cascades instead
    of hard-deleting (delete_model), and the built-in bulk "Delete selected"
    action -- which operates via queryset.delete() and would otherwise bypass
    delete_model() entirely -- is removed (get_actions) so it can't be used
    to defeat soft-delete in bulk.
    """

    def get_queryset(self, request):
        manager = getattr(self.model, "all_objects", None)
        qs = manager.all() if manager is not None else super().get_queryset(request)
        ordering = self.get_ordering(request)
        return qs.order_by(*ordering) if ordering else qs

    def get_actions(self, request):
        actions = super().get_actions(request)
        actions.pop("delete_selected", None)
        return actions

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        log_audit(
            user=request.user,
            action="CREATE" if not change else "UPDATE",
            target=obj,
            ip_address=client_ip(request),
        )

    def delete_model(self, request, obj):
        log_audit(
            user=request.user,
            action="DELETE",
            target=obj,
            ip_address=client_ip(request),
        )
        deactivate_with_cascade(obj)


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ("user", "action", "target_type", "target_id", "ip_address", "created_at")
    list_filter = ("action", "created_at")
    search_fields = ("user__username", "target_type")
    readonly_fields = (
        "user",
        "action",
        "target_type",
        "target_id",
        "ip_address",
        "details",
        "created_at",
        "updated_at",
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
