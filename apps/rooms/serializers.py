from rest_framework import serializers

from apps.centers.models import MedicalCenter
from apps.core.serializers import CoreModelSerializer
from apps.rooms.models import Room, RoomType


class RoomTypeSerializer(CoreModelSerializer):
    class Meta:
        model = RoomType
        fields = ["id", "name", "active"]

    def to_internal_value(self, data):
        # Normalize name to uppercase before DRF's UniqueValidator runs (it
        # runs before validate_name, so uppercasing there would be too late
        # to catch a same-name-different-case duplicate) -- the model's own
        # save() override is a defense-in-depth backstop for direct ORM use.
        if hasattr(data, "get") and isinstance(data.get("name"), str):
            data = {**data, "name": data["name"].upper()}
        return super().to_internal_value(data)


class RoomLiteSerializer(serializers.ModelSerializer):
    """Compact read-only representation for nesting inside other apps'
    serializers (e.g. DoctorProfileSerializer.rooms_detail) -- mirrors
    services' ServiceLiteSerializer pattern."""

    class Meta:
        model = Room
        fields = ["id", "name"]


class RoomSerializer(CoreModelSerializer):
    center_name = serializers.CharField(source="center.name", read_only=True)
    room_type_name = serializers.CharField(source="room_type.name", read_only=True)
    # Not editable in the frontend form (the Center field is hidden --
    # rooms always live in the org's default center) -- required=False lets
    # validate() below fill it in server-side instead of the client having
    # to supply it.
    center = serializers.PrimaryKeyRelatedField(queryset=MedicalCenter.objects.all(), required=False)

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

    def validate(self, attrs):
        # center is never collected from the Rooms create/edit form -- always
        # auto-filled from the org's default center when omitted, mirroring
        # apps/appointments/serializers.py's identical pattern.
        if "center" not in attrs or attrs.get("center") is None:
            if self.instance is None or self.instance.center_id is None:
                attrs["center"] = MedicalCenter.objects.filter(is_default=True).first()
        return attrs
