from django.contrib import admin

from apps.core.admin import AuditModelAdmin
from apps.systemsettings.models import SystemSettings


@admin.register(SystemSettings)
class SystemSettingsAdmin(AuditModelAdmin):
    """Registered under AuditModelAdmin so admin-side edits hit the same
    audit trail (and, via the post_save signal, the same cache
    invalidation) as API-side edits."""

    list_display = ("__str__", "updated_by", "updated_at")

    def has_add_permission(self, request):
        # Singleton: never allow creating a second row from the admin UI.
        return not SystemSettings.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False

    def save_model(self, request, obj, form, change):
        obj.updated_by = request.user
        super().save_model(request, obj, form, change)
