from django.contrib import admin

from apps.appointments.models import Appointment
from apps.core.admin import AuditModelAdmin


@admin.register(Appointment)
class AppointmentAdmin(AuditModelAdmin):
    list_display = ("patient", "doctor", "center", "date_time", "status", "created_by")
    list_filter = ("status", "center")
    search_fields = (
        "patient__first_name",
        "patient__last_name",
        "doctor__user__username",
    )
