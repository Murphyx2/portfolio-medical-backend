from django.contrib import admin

from apps.core.admin import AuditModelAdmin
from apps.reportes.models import ReportDefinition, ReportPack


@admin.register(ReportDefinition)
class ReportDefinitionAdmin(AuditModelAdmin):
    list_display = ["name", "category", "engine_key", "active"]


@admin.register(ReportPack)
class ReportPackAdmin(AuditModelAdmin):
    list_display = ["name", "periodicity", "engine_key", "active"]
