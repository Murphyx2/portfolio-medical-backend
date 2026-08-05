from django.contrib import admin

from apps.ars.models import ARS, ARSProgram


@admin.register(ARS)
class ARSAdmin(admin.ModelAdmin):
    list_display = ("ars_id", "name", "program_count")
    search_fields = ("ars_id", "name")

    @admin.display(description="Programs")
    def program_count(self, obj):
        return obj.programs.count()


@admin.register(ARSProgram)
class ARSProgramAdmin(admin.ModelAdmin):
    list_display = ("name", "ars")
    list_filter = ("ars",)
