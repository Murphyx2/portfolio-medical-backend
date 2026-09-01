from django.contrib import admin

from apps.communications.models import CommunicationsSettings, Delivery, Message, OptOut, Template
from apps.core.admin import AuditModelAdmin


@admin.register(CommunicationsSettings)
class CommunicationsSettingsAdmin(AuditModelAdmin):
    list_display = ("__str__", "whatsapp_master_enabled", "updated_by", "updated_at")

    def has_add_permission(self, request):
        return not CommunicationsSettings.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False

    def save_model(self, request, obj, form, change):
        obj.updated_by = request.user
        super().save_model(request, obj, form, change)


@admin.register(Template)
class TemplateAdmin(AuditModelAdmin):
    list_display = ("channel", "kind", "provider_name", "language", "is_active")
    list_filter = ("channel", "kind", "is_active")


@admin.register(Message)
class MessageAdmin(AuditModelAdmin):
    list_display = ("channel", "audience", "kind", "status", "created_by", "created_at")
    list_filter = ("channel", "audience", "kind", "status")
    readonly_fields = ("created_at", "updated_at")

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Delivery)
class DeliveryAdmin(AuditModelAdmin):
    list_display = ("message", "status", "attempts", "sent_at", "created_at")
    list_filter = ("status",)

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(OptOut)
class OptOutAdmin(AuditModelAdmin):
    list_display = ("patient", "reason", "created_at")

    def has_delete_permission(self, request, obj=None):
        return False
