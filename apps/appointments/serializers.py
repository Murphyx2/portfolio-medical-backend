from rest_framework import serializers

from apps.appointments.models import Appointment
from apps.core.masking import apply_masking
from apps.core.serializers import CoreModelSerializer
from apps.patients.models import Patient
from apps.doctors.models import DoctorProfile


class PatientLiteSerializer(serializers.ModelSerializer):
    full_name = serializers.ReadOnlyField()

    class Meta:
        model = Patient
        fields = ["id", "full_name", "gender"]


class DoctorLiteSerializer(serializers.ModelSerializer):
    full_name = serializers.ReadOnlyField()

    class Meta:
        model = DoctorProfile
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
        return obj.created_by.get_full_name() or obj.created_by.username

    def validate_doctor(self, value):
        request = self.context.get("request")
        user = getattr(request, "user", None) if request else None
        if user and user.is_authenticated and user.is_doctor:
            if not hasattr(user, "doctor_profile") or value.id != user.doctor_profile.id:
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
