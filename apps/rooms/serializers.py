from rest_framework import serializers

from apps.core.services import can_view_inactive
from apps.rooms.models import Room, RoomType


class RoomTypeSerializer(serializers.ModelSerializer):
    class Meta:
        model = RoomType
        fields = ["id", "name", "active"]

    def get_fields(self):
        fields = super().get_fields()
        request = self.context.get("request")
        user = getattr(request, "user", None) if request else None
        if not can_view_inactive(user):
            fields["active"].read_only = True
        return fields


class RoomSerializer(serializers.ModelSerializer):
    center_name = serializers.CharField(source="center.name", read_only=True)
    room_type_name = serializers.CharField(source="room_type.name", read_only=True)

    class Meta:
        model = Room
        fields = [
            "id",
            "code",
            "name",
            "room_type",
            "room_type_name",
            "center",
            "center_name",
            "floor_area",
            "capacity",
            "notes",
            "created_at",
            "updated_at",
            "active",
        ]
        read_only_fields = ["created_at", "updated_at"]

    def get_fields(self):
        fields = super().get_fields()
        request = self.context.get("request")
        user = getattr(request, "user", None) if request else None
        if not can_view_inactive(user):
            fields["active"].read_only = True
        return fields
