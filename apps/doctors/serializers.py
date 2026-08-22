from django.contrib.auth import get_user_model
from rest_framework import serializers

from apps.core.masking import mask_doctor_contact
from apps.core.permissions import IsAdminOrCenterManager
from apps.core.serializers import CoreModelSerializer
from apps.core.services import can_write_center, is_own_doctor_relation
from apps.core.validators import validate_phone
from apps.doctors.models import DoctorPhoneNumber, DoctorProfile, DoctorSchedule
from apps.rooms.models import Room
from apps.rooms.serializers import RoomLiteSerializer
from apps.services.models import Service
from apps.services.serializers import ServiceLiteSerializer


class DoctorLiteSerializer(serializers.ModelSerializer):
    """Canonical base for cross-app "lite" doctor nesting (appointments and
    encounters each used to declare their own independent copy). Consumers
    subclass and override ``Meta.fields`` to their own subset, same pattern
    as ``apps.patients.serializers.PatientSummarySerializer`` and the
    ``ServiceLiteSerializer`` convention this mirrors."""

    full_name = serializers.ReadOnlyField()

    class Meta:
        model = DoctorProfile
        fields = ["id", "code", "full_name"]


class DoctorPhoneNumberSerializer(serializers.ModelSerializer):
    class Meta:
        model = DoctorPhoneNumber
        fields = ["id", "phone"]

    def validate_phone(self, value: str) -> str:
        return validate_phone(value)


class DoctorProfileSerializer(CoreModelSerializer):
    full_name = serializers.CharField(read_only=True)
    username = serializers.CharField(source="user.username", read_only=True)
    user_id = serializers.IntegerField(source="user.id", read_only=True)
    user = serializers.PrimaryKeyRelatedField(
        queryset=get_user_model().objects.all(),
        write_only=True,
    )
    default_room_name = serializers.CharField(
        source="default_room.name", read_only=True, default=None
    )
    services = serializers.PrimaryKeyRelatedField(
        many=True, required=False, queryset=Service.objects.filter(active=True)
    )
    services_detail = ServiceLiteSerializer(source="services", many=True, read_only=True)
    rooms = serializers.PrimaryKeyRelatedField(
        many=True, required=False, queryset=Room.objects.filter(active=True)
    )
    rooms_detail = RoomLiteSerializer(source="rooms", many=True, read_only=True)
    # Additional phone numbers beyond the primary `contact_phone` field --
    # write side replaces the full set on every save (delete-and-recreate),
    # mirroring PatientSerializer.extra_phones.
    extra_phones = DoctorPhoneNumberSerializer(many=True, required=False)

    class Meta:
        model = DoctorProfile
        fields = [
            "id",
            "user",
            "user_id",
            "username",
            "full_name",
            "code",
            "license_number",
            "contact_phone",
            "extra_phones",
            "contact_email",
            "bio",
            "default_room",
            "default_room_name",
            "services",
            "services_detail",
            "rooms",
            "rooms_detail",
            "active",
        ]
        read_only_fields = ["code"]

    def to_representation(self, instance):
        data = super().to_representation(instance)
        return mask_doctor_contact(data, self._request_user(), instance)

    def validate_contact_phone(self, value: str) -> str:
        return validate_phone(value)

    def create(self, validated_data):
        extra_phones = validated_data.pop("extra_phones", None)
        doctor = super().create(validated_data)
        if extra_phones:
            DoctorPhoneNumber.objects.bulk_create(
                DoctorPhoneNumber(doctor=doctor, phone=p["phone"]) for p in extra_phones
            )
        return doctor

    def update(self, instance, validated_data):
        extra_phones = validated_data.pop("extra_phones", None)
        doctor = super().update(instance, validated_data)
        if extra_phones is not None:
            doctor.extra_phones.all().delete()
            DoctorPhoneNumber.objects.bulk_create(
                DoctorPhoneNumber(doctor=doctor, phone=p["phone"]) for p in extra_phones
            )
        return doctor

    def validate_services(self, value):
        # Read access to services_detail is open to any staff role (see
        # DoctorProfileViewSet's IsStaffUser read gate); only ADMIN/
        # CENTER_MANAGER may change *which* services a doctor offers. DRF
        # permission classes are method-wide (a PATCH could touch other
        # fields too), so this is enforced per-field here, reusing the same
        # has_permission() the services app itself gates writes with rather
        # than re-deriving the role check.
        if "services" in self.initial_data:
            request = self.context.get("request")
            if not IsAdminOrCenterManager().has_permission(request, None):
                raise serializers.ValidationError(
                    "Only admins or center managers may edit a doctor's services."
                )
        return value

    def validate_rooms(self, value):
        # Same write gate as validate_services above -- rooms is the same
        # kind of doctor-availability assignment as services.
        if "rooms" in self.initial_data:
            request = self.context.get("request")
            if not IsAdminOrCenterManager().has_permission(request, None):
                raise serializers.ValidationError(
                    "Only admins or center managers may edit a doctor's rooms."
                )
        return value

    def validate(self, attrs):
        # The view's write permission (IsAdminOrITOrCenterManager) admits a
        # CENTER_MANAGER at the request level so they can reach the
        # `services`/`rooms` fields above -- this is what actually confines
        # them to *only* those fields, since they otherwise have none of
        # IT's general doctor-profile write access.
        request = self.context.get("request")
        user = getattr(request, "user", None) if request else None
        if user and getattr(user, "is_center_manager", False) and not getattr(
            user, "is_admin", False
        ):
            other_fields = set(self.initial_data.keys()) - {"services", "rooms"}
            if other_fields:
                raise serializers.ValidationError(
                    "Center managers may only edit a doctor's services and rooms."
                )
        return attrs

    def validate_user(self, value):
        if self.instance and self.instance.user_id == value.id:
            return value
        if DoctorProfile.objects.filter(user=value).exists():
            raise serializers.ValidationError(
                "This user already has a doctor profile."
            )
        return value


class DoctorScheduleSerializer(CoreModelSerializer):
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

    def get_weekday_label(self, obj):
        return obj.get_weekday_display()

    def validate_doctor(self, value):
        request = self.context.get("request")
        user = getattr(request, "user", None) if request else None
        if user and user.is_authenticated and not is_own_doctor_relation(user, value):
            raise serializers.ValidationError(
                "Doctors may only manage schedules for themselves."
            )
        return value

    def validate(self, attrs):
        request = self.context.get("request")
        user = getattr(request, "user", None) if request else None
        doctor = attrs.get("doctor")
        center = attrs.get("center")
        if user and user.is_authenticated and doctor and center and not can_write_center(user, center):
            raise serializers.ValidationError(
                {"center": "You are not approved to work at this center."}
            )
        return attrs
