from django.contrib import admin

from apps.core.models import AuditLog


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
