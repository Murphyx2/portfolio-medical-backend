from rest_framework import serializers

from apps.centers.models import DoctorCenterBinding, MedicalCenter
from apps.core.validators import validate_phone


class MedicalCenterSerializer(serializers.ModelSerializer):
    doctor_count = serializers.IntegerField(source="doctor_bindings.count", read_only=True)

    class Meta:
        model = MedicalCenter
        fields = ["id", "name", "code", "address", "phone", "email", "doctor_count"]

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
        ]
        read_only_fields = ["approved_by"]
