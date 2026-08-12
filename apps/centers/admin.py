from django.contrib import admin

from apps.centers.models import DoctorCenterBinding, MedicalCenter
from apps.core.admin import AuditModelAdmin


@admin.register(MedicalCenter)
class MedicalCenterAdmin(AuditModelAdmin):
    list_display = ("name", "code", "phone", "email", "active")
    list_filter = ("active",)
    search_fields = ("name", "code")


@admin.register(DoctorCenterBinding)
class DoctorCenterBindingAdmin(AuditModelAdmin):
    list_display = ("doctor", "center", "approved", "approved_by", "created_at", "active")
    list_filter = ("approved", "center", "active")
    search_fields = ("doctor__user__username", "center__name")
