from django.contrib import admin

from apps.core.admin import AuditModelAdmin
from apps.prescriptions.models import Receta, RecetaLinea


class RecetaLineaInline(admin.TabularInline):
    model = RecetaLinea
    extra = 0


@admin.register(Receta)
class RecetaAdmin(AuditModelAdmin):
    list_display = ("id", "patient", "centro", "medico", "fecha", "estado", "active")
    list_filter = ("estado", "centro", "active")
    search_fields = ("patient__search_name", "medico__user__username")
    inlines = [RecetaLineaInline]
