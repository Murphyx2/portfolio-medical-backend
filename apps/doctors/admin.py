from django.contrib import admin

from apps.core.admin import AuditModelAdmin
from apps.doctors.models import DoctorProfile, DoctorSchedule


@admin.register(DoctorProfile)
class DoctorProfileAdmin(AuditModelAdmin):
    list_display = ("full_name", "license_number", "contact_phone", "active")
    list_filter = ("active",)
    search_fields = ("user__username", "user__first_name", "user__last_name", "license_number")


@admin.register(DoctorSchedule)
class DoctorScheduleAdmin(AuditModelAdmin):
    list_display = ("doctor", "center", "weekday", "start_time", "end_time", "active")
    list_filter = ("weekday", "center", "active")
