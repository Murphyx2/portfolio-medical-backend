from django.contrib import admin

from apps.medicines.models import Medicine


@admin.register(Medicine)
class MedicineAdmin(admin.ModelAdmin):
    list_display = ("generic_name", "commercial_name", "concentration")
    search_fields = ("generic_name", "commercial_name")
