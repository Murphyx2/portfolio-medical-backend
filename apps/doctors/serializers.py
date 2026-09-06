from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.db import transaction
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


class DoctorAccountCreateSerializer(serializers.Serializer):
    """Write-only input for "Crear cuenta de usuario" on the médico form --
    creates the linked User in the same transaction as the DoctorProfile,
    mutually exclusive with passing `user` directly (see validate_user)."""

    username = serializers.CharField()
    password = serializers.CharField(write_only=True, style={"input_type": "password"})
    email = serializers.EmailField(required=False, allow_blank=True, default="")

    def validate_username(self, value):
        if get_user_model().objects.filter(username=value).exists():
            raise serializers.ValidationError("A user with this username already exists.")
        return value

    def validate_password(self, value):
        validate_password(value)
        return value


class DoctorProfileSerializer(CoreModelSerializer):
    first_name = serializers.CharField(max_length=150, allow_blank=False)
    # Optional, matching User.last_name's own laxity -- the Usuarios-
    # initiated "crear médico nuevo" flow seeds these from the user's own
    # Nombre/Apellido, which doesn't require Apellido either.
    last_name = serializers.CharField(max_length=150, required=False, allow_blank=True)
    full_name = serializers.CharField(read_only=True)
    username = serializers.CharField(source="user.username", read_only=True, default="")
    user_id = serializers.IntegerField(source="user.id", read_only=True, default=None)
    user = serializers.PrimaryKeyRelatedField(
        queryset=get_user_model().objects.all(),
        write_only=True,
        required=False,
        allow_null=True,
    )
    # Write-only alternative to `user`: creates a new Doctor/a-role login and
    # links it in the same request, instead of picking an existing one.
    create_account = DoctorAccountCreateSerializer(write_only=True, required=False)
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
            "create_account",
            "user_id",
            "username",
            "first_name",
            "last_name",
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

    def validate_license_number(self, value):
        # Normalize blank submissions to None rather than "" -- Postgres
        # allows multiple NULLs under a unique index but not multiple ""s.
        return value or None

    def validate(self, attrs):
        if attrs.get("user") and attrs.get("create_account"):
            raise serializers.ValidationError(
                {"create_account": "Choose either an existing account to link or create a new one, not both."}
            )
        return attrs

    @transaction.atomic
    def create(self, validated_data):
        extra_phones = validated_data.pop("extra_phones", None)
        create_account = validated_data.pop("create_account", None)
        if create_account:
            validated_data["user"] = self._create_account(create_account, validated_data)
        doctor = super().create(validated_data)
        if extra_phones:
            DoctorPhoneNumber.objects.bulk_create(
                DoctorPhoneNumber(doctor=doctor, phone=p["phone"]) for p in extra_phones
            )
        doctor.sync_linked_user_name()
        return doctor

    @transaction.atomic
    def update(self, instance, validated_data):
        extra_phones = validated_data.pop("extra_phones", None)
        create_account = validated_data.pop("create_account", None)
        if create_account:
            validated_data["user"] = self._create_account(create_account, validated_data)
        doctor = super().update(instance, validated_data)
        if extra_phones is not None:
            doctor.extra_phones.all().delete()
            DoctorPhoneNumber.objects.bulk_create(
                DoctorPhoneNumber(doctor=doctor, phone=p["phone"]) for p in extra_phones
            )
        doctor.sync_linked_user_name()
        return doctor

    def _create_account(self, data, doctor_data):
        User = get_user_model()
        user = User(
            username=data["username"],
            email=data.get("email", ""),
            first_name=doctor_data.get("first_name", ""),
            last_name=doctor_data.get("last_name", ""),
            role=User.Role.DOCTOR,
        )
        user.set_password(data["password"])
        user.save()
        return user

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

    def validate_user(self, value):
        if value is None:
            return value
        if self.instance and self.instance.user_id == value.id:
            return value
        if value.role != value.Role.DOCTOR:
            raise serializers.ValidationError(
                "Only users with the Doctor/a role can be linked to a médico."
            )
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
