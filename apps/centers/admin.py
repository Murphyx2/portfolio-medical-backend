from django.contrib import admin

from apps.centers.models import (
    DoctorCenterBinding,
    MedicalCenter,
    MedicalCenterEmail,
    MedicalCenterPhone,
)
from apps.core.admin import AuditModelAdmin


class MedicalCenterPhoneInline(admin.TabularInline):
    model = MedicalCenterPhone
    extra = 0


class MedicalCenterEmailInline(admin.TabularInline):
    model = MedicalCenterEmail
    extra = 0


@admin.register(MedicalCenter)
class MedicalCenterAdmin(AuditModelAdmin):
    list_display = ("name", "code", "phone", "email", "is_default", "active")
    list_filter = ("is_default", "active")
    search_fields = ("name", "code")
    inlines = [MedicalCenterPhoneInline, MedicalCenterEmailInline]


@admin.register(DoctorCenterBinding)
class DoctorCenterBindingAdmin(AuditModelAdmin):
    list_display = ("doctor", "center", "approved", "approved_by", "created_at", "active")
    list_filter = ("approved", "center", "active")
    search_fields = ("doctor__user__username", "center__name")
