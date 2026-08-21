from rest_framework import serializers

from apps.appointments.models import Appointment
from apps.core.masking import apply_masking
from apps.core.serializers import CoreModelSerializer, full_name_or_username
from apps.core.services import is_own_doctor_relation
from apps.doctors.serializers import DoctorLiteSerializer as _DoctorLiteBase
from apps.patients.serializers import PatientSummarySerializer


class PatientLiteSerializer(PatientSummarySerializer):
    # Masked subset (see AppointmentSerializer's
    # apply_masking(masked_nested=(("patient_info", (...)),)) below): full_name.
    class Meta(PatientSummarySerializer.Meta):
        fields = ["id", "full_name", "gender"]


class DoctorLiteSerializer(_DoctorLiteBase):
    class Meta(_DoctorLiteBase.Meta):
        fields = ["id", "full_name"]


class AppointmentSerializer(CoreModelSerializer):
    patient_info = PatientLiteSerializer(source="patient", read_only=True)
    doctor_info = DoctorLiteSerializer(source="doctor", read_only=True)
    center_name = serializers.CharField(source="center.name", read_only=True, default=None)
    created_by_name = serializers.SerializerMethodField()

    class Meta:
        model = Appointment
        fields = [
            "id",
            "patient",
            "patient_info",
            "doctor",
            "doctor_info",
            "center",
            "center_name",
            "date_time",
            "duration_minutes",
            "status",
            "notes",
            "created_by",
            "created_by_name",
            "created_at",
            "active",
        ]
        read_only_fields = ["id", "created_by", "created_at"]

    def get_created_by_name(self, obj):
        return full_name_or_username(obj.created_by)

    def validate_doctor(self, value):
        request = self.context.get("request")
        user = getattr(request, "user", None) if request else None
        if user and user.is_authenticated and not is_own_doctor_relation(user, value):
            raise serializers.ValidationError(
                "Doctors may only manage appointments for themselves."
            )
        return value

    def to_representation(self, instance):
        data = super().to_representation(instance)
        return apply_masking(
            data,
            self._request_user(),
            masked_fields=("created_by_name", "notes"),
            masked_nested=(("patient_info", ("full_name",)),),
        )
