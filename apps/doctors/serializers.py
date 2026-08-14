from django.contrib.auth import get_user_model
from rest_framework import serializers

from apps.centers.models import DoctorCenterBinding
from apps.core.services import can_view_inactive
from apps.core.validators import validate_phone
from apps.doctors.models import DoctorProfile, DoctorSchedule
from apps.patients.serializers import _mask


def _request_user(context):
    request = context.get("request")
    return getattr(request, "user", None) if request else None


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
            "active",
        ]

    def get_fields(self):
        fields = super().get_fields()
        if not can_view_inactive(_request_user(self.context)):
            fields["active"].read_only = True
        return fields

    def to_representation(self, instance):
        data = super().to_representation(instance)
        request = self.context.get("request") if self.context else None
        user = getattr(request, "user", None) if request else None
        is_self = bool(user and instance.user_id == getattr(user, "id", None))
        if user and not (user.is_admin or user.is_it) and not is_self:
            # Doctor contact PII (M-03) is only for admins/IT and the doctor
            # themself; other staff keep name/specialty but see masked contact.
            # Exception: receptionists need unmasked phone/email to coordinate
            # appointments, but license_number/bio stay hidden from them too.
            is_receptionist = getattr(user, "is_receptionist", False)
            if data.get("license_number"):
                data["license_number"] = _mask(str(data["license_number"]))
            if not is_receptionist:
                if data.get("contact_phone"):
                    data["contact_phone"] = _mask(str(data["contact_phone"]))
                if data.get("contact_email"):
                    data["contact_email"] = _mask(str(data["contact_email"]))
            data["bio"] = None
        return data

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
            "active",
        ]
        read_only_fields = ["weekday_label"]

    weekday_label = serializers.SerializerMethodField()

    def get_fields(self):
        fields = super().get_fields()
        if not can_view_inactive(_request_user(self.context)):
            fields["active"].read_only = True
        return fields

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
