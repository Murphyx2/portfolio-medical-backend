from django.contrib import admin

from apps.core.admin import AuditModelAdmin
from apps.rooms.models import Room


@admin.register(Room)
class RoomAdmin(AuditModelAdmin):
    list_display = ("code", "name", "room_type", "center", "capacity", "active")
    list_filter = ("active", "room_type", "center")
    search_fields = ("code", "name", "floor_area")
