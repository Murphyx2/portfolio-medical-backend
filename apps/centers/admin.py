from django.contrib import admin

from apps.centers.models import DoctorCenterBinding, MedicalCenter


@admin.register(MedicalCenter)
class MedicalCenterAdmin(admin.ModelAdmin):
    list_display = ("name", "code", "phone", "email")
    search_fields = ("name", "code")


@admin.register(DoctorCenterBinding)
class DoctorCenterBindingAdmin(admin.ModelAdmin):
    list_display = ("doctor", "center", "approved", "approved_by", "created_at")
    list_filter = ("approved", "center")
    search_fields = ("doctor__user__username", "center__name")
