from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.db import transaction
from rest_framework import serializers

User = get_user_model()


class DoctorProfileLinkSerializer(serializers.Serializer):
    """Write-only nested input on the Usuarios form: required whenever
    role=DOCTOR, either linking an existing unlinked médico or creating one
    inline (see USUARIO_MEDICO_LINK_REQUIREMENTS.md). `doctors.DoctorProfile`
    is imported locally inside the methods that need it, not at module
    level -- `accounts` reaching into `doctors` is a deliberate, contained
    exception to the usual one-directional (`doctors` -> `accounts`)
    app coupling, scoped to this one link/create flow."""

    mode = serializers.ChoiceField(choices=["link", "create"])
    doctor_profile_id = serializers.IntegerField(required=False)
    license_number = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    contact_phone = serializers.CharField(required=False, allow_blank=True)
    extra_phones = serializers.ListField(child=serializers.CharField(), required=False)
    contact_email = serializers.CharField(required=False, allow_blank=True)
    bio = serializers.CharField(required=False, allow_blank=True)
    services = serializers.ListField(child=serializers.IntegerField(), required=False)
    rooms = serializers.ListField(child=serializers.IntegerField(), required=False)

    def validate(self, attrs):
        from apps.doctors.models import DoctorProfile

        if attrs["mode"] == "link":
            doctor_id = attrs.get("doctor_profile_id")
            if not doctor_id:
                raise serializers.ValidationError(
                    {"doctor_profile_id": "Select a médico to link."}
                )
            try:
                doctor = DoctorProfile.objects.get(
                    pk=doctor_id, user__isnull=True, active=True
                )
            except DoctorProfile.DoesNotExist as exc:
                raise serializers.ValidationError(
                    {"doctor_profile_id": "This médico is no longer available to link."}
                ) from exc
            attrs["_doctor_profile"] = doctor
        return attrs


def _link_or_create_doctor_profile(user, payload):
    """Shared by UserCreateSerializer.create() and UserSerializer.update():
    resolves the validated `doctor_profile` payload into either linking an
    already-fetched unlinked médico to `user`, or creating a new one.

    The médico is the authoritative name for a linked Doctor/a user: linking
    an already-named médico overwrites the user's Nombre/Apellido with the
    médico's (sync_linked_user_name()); only a legacy, still-blank médico
    falls back to being seeded from the user instead."""
    from apps.doctors.models import DoctorPhoneNumber, DoctorProfile

    if payload["mode"] == "link":
        doctor = payload["_doctor_profile"]
        doctor.user = user
        if not (doctor.first_name or doctor.last_name):
            doctor.first_name = user.first_name
            doctor.last_name = user.last_name
        doctor.save()
        doctor.sync_linked_user_name()
        return doctor

    doctor = DoctorProfile.objects.create(
        user=user,
        first_name=user.first_name,
        last_name=user.last_name,
        license_number=payload.get("license_number") or None,
        contact_phone=payload.get("contact_phone", ""),
        contact_email=payload.get("contact_email", ""),
        bio=payload.get("bio", ""),
    )
    services = payload.get("services")
    if services:
        doctor.services.set(services)
    rooms = payload.get("rooms")
    if rooms:
        doctor.rooms.set(rooms)
    extra_phones = payload.get("extra_phones")
    if extra_phones:
        DoctorPhoneNumber.objects.bulk_create(
            DoctorPhoneNumber(doctor=doctor, phone=p) for p in extra_phones if p
        )
    return doctor


class UserSerializer(serializers.ModelSerializer):
    full_name = serializers.CharField(source="get_full_name", read_only=True)
    is_locked = serializers.BooleanField(read_only=True)
    center_name = serializers.CharField(source="center.name", read_only=True, default=None)
    # Only meaningful (and required) when role is/becomes DOCTOR and the
    # user has no médico linked yet -- see validate()/update() below.
    doctor_profile = DoctorProfileLinkSerializer(write_only=True, required=False)

    class Meta:
        model = User
        fields = [
            "id",
            "username",
            "email",
            "first_name",
            "last_name",
            "full_name",
            "role",
            "center",
            "center_name",
            "doctor_profile",
            "is_active",
            "is_locked",
            "locked_until",
            "last_login",
            "date_joined",
        ]
        read_only_fields = ["id", "date_joined", "locked_until", "last_login"]

    def validate(self, attrs):
        _guard_role_assignment(self.context, attrs, instance=self.instance)
        _guard_doctor_profile_requirement(attrs, instance=self.instance)
        return attrs

    @transaction.atomic
    def update(self, instance, validated_data):
        doctor_profile_payload = validated_data.pop("doctor_profile", None)
        was_doctor = instance.role == User.Role.DOCTOR
        new_role = validated_data.get("role", instance.role)
        user = super().update(instance, validated_data)
        if was_doctor and new_role != User.Role.DOCTOR:
            # Role changed away from Doctor/a: unconditionally unlink the
            # médico server-side (the frontend confirm dialog is UX only,
            # not the only safeguard). The médico row is never deleted.
            profile = getattr(user, "doctor_profile", None)
            if profile is not None:
                profile.user = None
                profile.save(update_fields=["user"])
        elif new_role == User.Role.DOCTOR and doctor_profile_payload and not getattr(user, "doctor_profile", None):
            _link_or_create_doctor_profile(user, doctor_profile_payload)
        return user


class UserCreateSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, style={"input_type": "password"})
    doctor_profile = DoctorProfileLinkSerializer(write_only=True, required=False)

    class Meta:
        model = User
        fields = [
            "id",
            "username",
            "email",
            "first_name",
            "last_name",
            "password",
            "role",
            "center",
            "doctor_profile",
            "is_active",
        ]

    def validate_password(self, value):
        validate_password(value)
        return value

    def validate(self, attrs):
        _guard_role_assignment(self.context, attrs, instance=self.instance)
        _guard_doctor_profile_requirement(attrs, instance=None)
        return attrs

    @transaction.atomic
    def create(self, validated_data):
        password = validated_data.pop("password")
        doctor_profile_payload = validated_data.pop("doctor_profile", None)
        user = User(**validated_data)
        user.set_password(password)
        user.save()
        if user.role == User.Role.DOCTOR and doctor_profile_payload:
            _link_or_create_doctor_profile(user, doctor_profile_payload)
        return user


def _guard_doctor_profile_requirement(attrs, instance=None):
    """Doctor/a role requires a médico link/create payload unless the user
    (on edit) already has one linked -- see DoctorProfileLinkSerializer."""
    new_role = attrs.get("role", instance.role if instance else None)
    if new_role != User.Role.DOCTOR:
        return
    already_linked = bool(instance and getattr(instance, "doctor_profile", None))
    if not already_linked and not attrs.get("doctor_profile"):
        raise serializers.ValidationError(
            {"doctor_profile": "You must link or create a doctor profile."}
        )


def _guard_role_assignment(context, attrs, instance=None):
    """Only admins may assign the ADMIN role or modify admin accounts."""
    request = context.get("request") if context else None
    user = getattr(request, "user", None) if request else None
    if user is None or not getattr(user, "is_authenticated", False):
        return
    if user.is_admin:
        return
    if attrs.get("role") == User.Role.ADMIN:
        raise serializers.ValidationError(
            {"role": "Only admins can assign the ADMIN role."}
        )
    if instance is not None and instance.is_admin:
        raise serializers.ValidationError(
            {"role": "Only admins can modify admin accounts."}
        )


class AdminSetPasswordSerializer(serializers.Serializer):
    """Admin-initiated password reset (distinct from a self-service change:
    no old-password confirmation, since the acting admin isn't the account
    owner)."""

    password = serializers.CharField(write_only=True, style={"input_type": "password"})

    def validate_password(self, value):
        validate_password(value, user=self.context.get("target_user"))
        return value


class LoginSerializer(serializers.Serializer):
    username = serializers.CharField()
    password = serializers.CharField(write_only=True, style={"input_type": "password"})


class LoginResponseSerializer(serializers.Serializer):
    access = serializers.CharField()
    user = UserSerializer()
