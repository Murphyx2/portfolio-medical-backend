from rest_framework import serializers

from apps.core.serializers import CoreModelSerializer
from apps.rooms.models import Room, RoomType


class RoomTypeSerializer(CoreModelSerializer):
    class Meta:
        model = RoomType
        fields = ["id", "name", "active"]


class RoomSerializer(CoreModelSerializer):
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
