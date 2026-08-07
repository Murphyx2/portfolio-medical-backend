from django.contrib import admin

from apps.ars.models import ARS, ARSProgram
from apps.core.admin import AuditModelAdmin


@admin.register(ARS)
class ARSAdmin(AuditModelAdmin):
    list_display = ("ars_id", "name", "program_count")
    search_fields = ("ars_id", "name")

    @admin.display(description="Programs")
    def program_count(self, obj):
        return obj.programs.count()


@admin.register(ARSProgram)
class ARSProgramAdmin(AuditModelAdmin):
    list_display = ("name", "ars")
    list_filter = ("ars",)
