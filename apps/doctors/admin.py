from django.contrib import admin

from apps.doctors.models import DoctorProfile, DoctorSchedule


@admin.register(DoctorProfile)
class DoctorProfileAdmin(admin.ModelAdmin):
    list_display = ("full_name", "specialty", "license_number", "contact_phone")
    search_fields = ("user__username", "user__first_name", "user__last_name", "license_number")


@admin.register(DoctorSchedule)
class DoctorScheduleAdmin(admin.ModelAdmin):
    list_display = ("doctor", "center", "weekday", "start_time", "end_time")
    list_filter = ("weekday", "center")
