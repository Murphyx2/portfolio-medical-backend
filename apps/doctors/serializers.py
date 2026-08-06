from django.contrib.auth import get_user_model
from rest_framework import serializers

from apps.centers.models import DoctorCenterBinding
from apps.core.validators import validate_phone
from apps.doctors.models import DoctorProfile, DoctorSchedule


class DoctorProfileSerializer(serializers.ModelSerializer):
    full_name = serializers.CharField(read_only=True)
    username = serializers.CharField(source="user.username", read_only=True)
    user_id = serializers.IntegerField(source="user.id", read_only=True)
    user = serializers.PrimaryKeyRelatedField(
        queryset=get_user_model().objects.all(),
        write_only=True,
    )

    class Meta:
        model = DoctorProfile
        fields = [
            "id",
            "user",
            "user_id",
            "username",
            "full_name",
            "specialty",
            "license_number",
            "contact_phone",
            "contact_email",
            "bio",
        ]

    def validate_contact_phone(self, value: str) -> str:
        return validate_phone(value)

    def validate_user(self, value):
        if self.instance and self.instance.user_id == value.id:
            return value
        if DoctorProfile.objects.filter(user=value).exists():
            raise serializers.ValidationError(
                "This user already has a doctor profile."
            )
        return value


class DoctorScheduleSerializer(serializers.ModelSerializer):
    doctor_full_name = serializers.CharField(source="doctor.full_name", read_only=True)
    center_name = serializers.CharField(source="center.name", read_only=True)

    class Meta:
        model = DoctorSchedule
        fields = [
            "id",
            "doctor",
            "doctor_full_name",
            "center",
            "center_name",
            "weekday",
            "weekday_label",
            "start_time",
            "end_time",
        ]
        read_only_fields = ["weekday_label"]

    weekday_label = serializers.SerializerMethodField()

    def get_weekday_label(self, obj):
        return obj.get_weekday_display()

    def validate_doctor(self, value):
        request = self.context.get("request")
        user = getattr(request, "user", None) if request else None
        if user and user.is_authenticated and user.is_doctor:
            if not hasattr(user, "doctor_profile") or value.id != user.doctor_profile.id:
                raise serializers.ValidationError(
                    "Doctors may only manage schedules for themselves."
                )
        return value

    def validate(self, attrs):
        request = self.context.get("request")
        user = getattr(request, "user", None) if request else None
        doctor = attrs.get("doctor")
        center = attrs.get("center")
        if user and user.is_authenticated and user.is_doctor and doctor and center:
            if not DoctorCenterBinding.objects.filter(
                doctor=doctor, center=center, approved=True
            ).exists():
                raise serializers.ValidationError(
                    {"center": "You are not approved to work at this center."}
                )
        return attrs
