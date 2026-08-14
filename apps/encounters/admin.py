from django.contrib import admin

from apps.core.admin import AuditModelAdmin
from apps.encounters.models import Encounter, EncounterDiagnosis, EncounterService, EncounterType


class EncounterDiagnosisInline(admin.TabularInline):
    model = EncounterDiagnosis
    extra = 0


class EncounterServiceInline(admin.TabularInline):
    model = EncounterService
    extra = 0


@admin.register(EncounterType)
class EncounterTypeAdmin(AuditModelAdmin):
    list_display = ("name", "requires_diagnosis", "active")
    list_filter = ("active", "requires_diagnosis")
    search_fields = ("name",)


@admin.register(Encounter)
class EncounterAdmin(AuditModelAdmin):
    list_display = (
        "encounter_number",
        "patient",
        "doctor",
        "status",
        "priority",
        "center",
        "active",
    )
    list_filter = ("status", "priority", "active", "encounter_type", "center")
    search_fields = ("encounter_number", "patient__search_name")
    inlines = [EncounterDiagnosisInline, EncounterServiceInline]
