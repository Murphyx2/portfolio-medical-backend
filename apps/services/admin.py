from django.contrib import admin

from apps.core.admin import AuditModelAdmin
from apps.services.models import Service, ServiceType


@admin.register(ServiceType)
class ServiceTypeAdmin(AuditModelAdmin):
    list_display = ("name", "active")
    list_filter = ("active",)
    search_fields = ("name",)


@admin.register(Service)
class ServiceAdmin(AuditModelAdmin):
    list_display = ("name", "simon", "type", "co_pago", "privado", "active")
    list_filter = ("active", "type")
    search_fields = ("name", "simon")
