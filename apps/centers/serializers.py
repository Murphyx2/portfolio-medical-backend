from rest_framework import serializers

from apps.centers.models import DoctorCenterBinding, MedicalCenter
from apps.core.services import can_view_inactive
from apps.core.validators import validate_phone


def _request_user(context):
    request = context.get("request")
    return getattr(request, "user", None) if request else None


class MedicalCenterSerializer(serializers.ModelSerializer):
    doctor_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = MedicalCenter
        fields = ["id", "name", "code", "address", "phone", "email", "is_default", "doctor_count", "active"]

    def get_fields(self):
        fields = super().get_fields()
        if not can_view_inactive(_request_user(self.context)):
            fields["active"].read_only = True
        return fields

    def validate_phone(self, value: str) -> str:
        return validate_phone(value)


class DoctorCenterBindingSerializer(serializers.ModelSerializer):
    doctor_full_name = serializers.CharField(source="doctor.full_name", read_only=True)
    center_name = serializers.CharField(source="center.name", read_only=True)

    class Meta:
        model = DoctorCenterBinding
        fields = [
            "id",
            "doctor",
            "doctor_full_name",
            "center",
            "center_name",
            "approved",
            "approved_by",
            "created_at",
            "active",
        ]
        read_only_fields = ["approved_by"]

    def get_fields(self):
        fields = super().get_fields()
        if not can_view_inactive(_request_user(self.context)):
            fields["active"].read_only = True
        return fields
