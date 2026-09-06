from django.contrib import admin

from apps.core.admin import AuditModelAdmin
from apps.medicines.models import Medicine


@admin.register(Medicine)
class MedicineAdmin(AuditModelAdmin):
    list_display = ("generic_name", "commercial_name", "concentration", "active")
    list_filter = ("active",)
    search_fields = ("generic_name", "commercial_name")
