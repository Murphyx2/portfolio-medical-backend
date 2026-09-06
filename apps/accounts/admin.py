from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from apps.accounts.models import User
from apps.core.admin import AuditModelAdmin


@admin.register(User)
class CustomUserAdmin(AuditModelAdmin, UserAdmin):
    list_display = ("username", "email", "first_name", "last_name", "role", "is_staff", "is_active")
    list_filter = ("role", "is_staff", "is_active")
    fieldsets = UserAdmin.fieldsets + (
        ("Role", {"fields": ("role",)}),
    )
    add_fieldsets = UserAdmin.add_fieldsets + (
        ("Role", {"fields": ("role",)}),
    )
