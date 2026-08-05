from django.contrib import admin

from apps.patients.models import Patient


@admin.register(Patient)
class PatientAdmin(admin.ModelAdmin):
    list_display = ("full_name", "gender", "birth_date")
    search_fields = ("first_name", "last_name")
    readonly_fields = ("created_at", "updated_at")
