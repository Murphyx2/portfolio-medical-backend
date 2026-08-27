from django.contrib import admin

from apps.core.admin import AuditModelAdmin
from apps.records.models import (
    APCategory,
    APType,
    MedicalRecord,
    RecordEntry,
    RecordFamilyCondition,
    RecordImage,
    RecordPersonalCondition,
)


class RecordImageInline(admin.TabularInline):
    model = RecordImage
    extra = 0


@admin.register(MedicalRecord)
class MedicalRecordAdmin(AuditModelAdmin):
    list_display = ("patient", "created_by", "last_visit_at", "active")
    list_filter = ("active",)
    search_fields = ("patient__first_name", "patient__last_name")
    inlines = [RecordImageInline]


@admin.register(RecordEntry)
class RecordEntryAdmin(admin.ModelAdmin):
    # Plain ModelAdmin, not AuditModelAdmin: RecordEntry has no `active`
    # field (drafts hard-delete, completed entries are immutable/never
    # deleted), so AuditModelAdmin's soft-delete-on-delete_model() would
    # silently no-op instead of removing the row.
    list_display = ("record", "author", "status", "completed_at")
    list_filter = ("status",)


@admin.register(RecordPersonalCondition)
class RecordPersonalConditionAdmin(admin.ModelAdmin):
    list_display = ("record", "ap_type", "custom_label", "is_custom")
    list_filter = ("is_custom",)


@admin.register(RecordFamilyCondition)
class RecordFamilyConditionAdmin(admin.ModelAdmin):
    list_display = ("record", "relationship", "ap_type", "custom_label", "is_custom")
    list_filter = ("relationship", "is_custom")


@admin.register(RecordImage)
class RecordImageAdmin(AuditModelAdmin):
    list_display = ("record", "caption", "uploaded_by", "active")
    list_filter = ("active",)


@admin.register(APCategory)
class APCategoryAdmin(AuditModelAdmin):
    list_display = ("name", "sort_order", "active")
    list_filter = ("active",)
    search_fields = ("name",)


@admin.register(APType)
class APTypeAdmin(AuditModelAdmin):
    list_display = ("name", "category", "sort_order", "active")
    list_filter = ("active", "category")
    search_fields = ("name",)
