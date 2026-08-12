from django.contrib import admin

from apps.core.admin import AuditModelAdmin
from apps.patients.models import Patient


@admin.register(Patient)
class PatientAdmin(AuditModelAdmin):
    list_display = ("full_name", "gender", "birth_date", "active")
    list_filter = ("active",)
    search_fields = ("first_name", "last_name")
    readonly_fields = ("created_at", "updated_at")
