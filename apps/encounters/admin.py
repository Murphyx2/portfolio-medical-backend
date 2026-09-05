from django.contrib import admin

from apps.core.admin import AuditModelAdmin
from apps.encounters.models import Encounter, EncounterDiagnosis, EncounterService


class EncounterDiagnosisInline(admin.TabularInline):
    model = EncounterDiagnosis
    extra = 0


class EncounterServiceInline(admin.TabularInline):
    model = EncounterService
    extra = 0


@admin.register(Encounter)
class EncounterAdmin(AuditModelAdmin):
    list_display = (
        "encounter_number",
        "patient",
        "status",
        "priority",
        "center",
        "active",
    )
    list_filter = ("status", "priority", "active", "service_type", "center")
    search_fields = ("encounter_number", "patient__search_name")
    inlines = [EncounterDiagnosisInline, EncounterServiceInline]
