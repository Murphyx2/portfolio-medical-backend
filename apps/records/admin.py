from django.contrib import admin

from apps.core.admin import AuditModelAdmin
from apps.records.models import ConsultationLog, MedicalRecord, RecordImage


class RecordImageInline(admin.TabularInline):
    model = RecordImage
    extra = 0


@admin.register(MedicalRecord)
class MedicalRecordAdmin(AuditModelAdmin):
    list_display = ("title", "patient", "created_by", "date")
    search_fields = ("title", "patient__first_name", "patient__last_name")
    inlines = [RecordImageInline]


@admin.register(ConsultationLog)
class ConsultationLogAdmin(AuditModelAdmin):
    list_display = ("patient", "doctor", "date")
    search_fields = ("patient__first_name", "patient__last_name", "doctor__username")


@admin.register(RecordImage)
class RecordImageAdmin(AuditModelAdmin):
    list_display = ("record", "caption", "uploaded_by")
