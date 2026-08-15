from rest_framework import serializers

from apps.centers.models import DoctorCenterBinding, MedicalCenter
from apps.core.serializers import CoreModelSerializer
from apps.core.validators import validate_phone


class MedicalCenterSerializer(CoreModelSerializer):
    doctor_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = MedicalCenter
        fields = ["id", "name", "code", "address", "phone", "email", "is_default", "doctor_count", "active"]

    def validate_phone(self, value: str) -> str:
        return validate_phone(value)


class DoctorCenterBindingSerializer(CoreModelSerializer):
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
