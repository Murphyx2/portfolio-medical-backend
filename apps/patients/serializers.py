from datetime import date
import re
import unicodedata

from django.core.exceptions import ValidationError as DjangoValidationError
from django.core.validators import validate_email
from rest_framework import serializers

from apps.centers.models import MedicalCenter
from apps.core.encryption import blind_index_digits
from apps.core.masking import apply_masking
from apps.core.serializers import CoreModelSerializer
from apps.core.services import can_write_center, program_belongs_to_ars
from apps.core.validators import validate_phone
from apps.patients.models import Patient, PatientGuardian, PatientPhoneNumber, patient_age

# validate() only re-checks cedula/guardian requiredness when one of these
# keys is present in the incoming attrs (or on create) -- otherwise a PATCH
# touching an unrelated field (e.g. "phone") would re-trigger the check
# against a blank cedula/guardians fallback and permanently lock out any
# existing minor whose cedula/guardian info isn't on file yet.
_GUARDIAN_TRIGGER_KEYS = (
    "birth_date",
    "has_guardian",
    "cedula",
    "guardians",
)


def _normalize_cedula_digits(value: str, *, field_label: str = "Cedula") -> str:
    """Shared by validate_cedula/validate_guardian_cedula. Strips separators
    from the formatted display form (e.g. "001-1234567-8") rather than
    requiring a pure digit string -- unlike NSS below, cedula input commonly
    carries dashes.
    """
    digits = re.sub(r"\D", "", str(value))
    if len(digits) != 11:
        raise serializers.ValidationError(f"{field_label} must contain exactly 11 digits.")
    return digits


def _normalize_nss_digits(value: str, *, field_label: str = "NSS") -> str:
    """Shared by validate_nss/validate_guardian_nss. NFKC folds fullwidth/
    halfwidth forms into ASCII (e.g. "１２３" -> "123"); anything that does
    not fold to ASCII digits (letters, symbols, dashes, other scripts) is
    rejected rather than stripped.
    """
    normalized = unicodedata.normalize("NFKC", str(value))
    if not normalized.isascii() or not normalized.isdigit():
        raise serializers.ValidationError(f"{field_label} must contain digits only.")
    if len(normalized) > 11:
        raise serializers.ValidationError(f"{field_label} must be at most 11 digits.")
    return normalized


class PatientSummarySerializer(serializers.ModelSerializer):
    """Canonical base for cross-app "lite"/"summary" patient nesting
    (records/appointments/encounters each used to declare their own
    independent copy with a different field subset). Consumers subclass and
    override ``Meta.fields`` to their own subset -- this centralizes the
    ``full_name``/``age`` declared fields and the ``patient_age`` call so a
    new field only needs `.get_age`/normalization logic written once, while
    each consumer keeps exactly the (narrower) field set it exposed before
    (deliberately not widened to the full union here: that would expose more
    PHI per response than each endpoint needs, even though masking still
    applies to what's returned -- see apply_masking() call sites in each
    subclass's owning serializer for the masked subset of *its* fields).
    """

    full_name = serializers.ReadOnlyField()
    age = serializers.SerializerMethodField()
    ars_name = serializers.CharField(source="ars.name", read_only=True, default=None)
    # Backward-compat surface: consumers (Encounters' nested patient_info,
    # the guardian-cedula icon on Patients/Encounters lists) still expect one
    # flat guardian_cedula value even though a patient can now have several
    # guardians on file -- this exposes the first one, same as before
    # guardians became a list. New code should read `.guardians` directly.
    guardian_cedula = serializers.SerializerMethodField()

    class Meta:
        model = Patient
        fields = [
            "id",
            "full_name",
            "age",
            "gender",
            "cedula",
            "nss",
            "allergies",
            "critical_conditions",
            "ars",
            "ars_name",
            "ars_program",
            "has_guardian",
            "guardian_cedula",
        ]

    def get_age(self, obj) -> int | None:
        return patient_age(obj)

    def get_guardian_cedula(self, obj) -> str:
        guardian = obj.primary_guardian
        return guardian.cedula if guardian else ""


class PatientPhoneNumberSerializer(serializers.ModelSerializer):
    class Meta:
        model = PatientPhoneNumber
        fields = ["id", "phone"]

    def validate_phone(self, value: str) -> str:
        return validate_phone(value)


class PatientGuardianSerializer(serializers.ModelSerializer):
    class Meta:
        model = PatientGuardian
        fields = ["id", "first_name", "last_name", "cedula", "nss", "phone"]

    def validate_cedula(self, value: str) -> str:
        if value:
            return _normalize_cedula_digits(value, field_label="Guardian cedula")
        return value

    def validate_nss(self, value: str) -> str:
        if not value:
            return value
        return _normalize_nss_digits(value, field_label="Guardian NSS")

    def validate_phone(self, value: str) -> str:
        return validate_phone(value)


class PatientSerializer(CoreModelSerializer):
    full_name = serializers.ReadOnlyField()
    age = serializers.SerializerMethodField()
    ars_name = serializers.CharField(source="ars.name", read_only=True, default=None)
    ars_program_name = serializers.CharField(
        source="ars_program.name", read_only=True, default=None
    )
    center_name = serializers.CharField(source="center.name", read_only=True, default=None)
    center_code = serializers.CharField(source="center.code", read_only=True, default=None)
    # Additional phone numbers beyond the primary `phone` field -- write side
    # replaces the full set on every save (delete-and-recreate), matching
    # the simplicity of the rest of this serializer's flat-field shape.
    extra_phones = PatientPhoneNumberSerializer(many=True, required=False)
    # Guardians/tutors on file -- same delete-and-recreate write shape as
    # extra_phones (a guardian has no independent identity worth preserving
    # across an edit).
    guardians = PatientGuardianSerializer(many=True, required=False)

    class Meta:
        model = Patient
        fields = [
            "id",
            "first_name",
            "last_name",
            "full_name",
            "birth_date",
            "age",
            "gender",
            "center",
            "center_name",
            "center_code",
            "phone",
            "extra_phones",
            "address",
            "email",
            "cedula",
            "nss",
            "ars",
            "ars_name",
            "ars_program",
            "ars_program_name",
            "has_guardian",
            "guardians",
            "allergies",
            "critical_conditions",
            "active",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["created_at", "updated_at"]

    def create(self, validated_data):
        extra_phones = validated_data.pop("extra_phones", None)
        guardians = validated_data.pop("guardians", None)
        patient = super().create(validated_data)
        if extra_phones:
            PatientPhoneNumber.objects.bulk_create(
                PatientPhoneNumber(patient=patient, phone=p["phone"]) for p in extra_phones
            )
        if guardians:
            # Not bulk_create: PatientGuardian.save() derives cedula_last4/
            # cedula_hash, which bulk_create would skip (it never calls
            # save()), leaving guardian-cedula search silently broken.
            for g in guardians:
                PatientGuardian.objects.create(patient=patient, **g)
        return patient

    def update(self, instance, validated_data):
        extra_phones = validated_data.pop("extra_phones", None)
        guardians = validated_data.pop("guardians", None)
        patient = super().update(instance, validated_data)
        if extra_phones is not None:
            patient.extra_phones.all().delete()
            PatientPhoneNumber.objects.bulk_create(
                PatientPhoneNumber(patient=patient, phone=p["phone"]) for p in extra_phones
            )
        if guardians is not None:
            patient.guardians.all().delete()
            for g in guardians:
                PatientGuardian.objects.create(patient=patient, **g)
        return patient

    def get_fields(self):
        fields = super().get_fields()
        # Birth_date/gender are required on both create and update -- a
        # patient can never be left/made without these (matches the
        # DB-level requiredness on the model fields). Cedula is conditionally
        # required -- see validate(): always required for adults, but only
        # required for minors when no guardian is on file (has_guardian=False).
        fields["cedula"].required = False
        fields["cedula"].allow_blank = True
        fields["birth_date"].required = True
        fields["birth_date"].allow_blank = False
        fields["gender"].required = True
        return fields

    def get_age(self, obj) -> int | None:
        return patient_age(obj)

    def _check_unique_digits(self, field_name: str, digits: str, message: str) -> None:
        # cedula/nss are encrypted at rest (non-deterministic ciphertext), so
        # uniqueness can only be checked via the deterministic blind-index
        # hash column -- the same column the DB constraint targets. Queries
        # the active-only default manager to match the constraint's
        # active=True condition (a soft-deleted patient's identifiers are
        # free to reuse).
        digest = blind_index_digits(digits)
        qs = Patient.objects.filter(**{f"{field_name}_hash": digest})
        if self.instance is not None:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise serializers.ValidationError(message)

    def validate_cedula(self, value: str) -> str:
        if value:
            digits = _normalize_cedula_digits(value)
            self._check_unique_digits(
                "cedula", digits, "A patient with this cedula already exists."
            )
            return digits
        return value

    def validate_phone(self, value: str) -> str:
        return validate_phone(value)

    def validate_email(self, value: str) -> str:
        if not value:
            return value
        try:
            validate_email(value)
        except DjangoValidationError:
            raise serializers.ValidationError("Enter a valid email address.")
        return value

    def validate_birth_date(self, value: str) -> str:
        if not value:
            raise serializers.ValidationError("Birth date is required.")
        try:
            bd = date.fromisoformat(value)
        except (TypeError, ValueError):
            raise serializers.ValidationError(
                "Birth date must be a valid date (YYYY-MM-DD)."
            )
        if bd > date.today():
            raise serializers.ValidationError("Birth date cannot be in the future.")
        return value

    def validate_nss(self, value: str) -> str:
        if not value:
            return value
        normalized = _normalize_nss_digits(value)
        self._check_unique_digits(
            "nss", normalized, "A patient with this NSS already exists."
        )
        return normalized

    def validate(self, attrs):
        ars = attrs.get("ars")
        if ars is None and self.instance is not None:
            ars = self.instance.ars
        program = attrs.get("ars_program")
        if not program_belongs_to_ars(ars, program):
            raise serializers.ValidationError(
                {"ars_program": "The selected program does not belong to the selected ARS."}
            )

        request = self.context.get("request")
        user = getattr(request, "user", None) if request else None
        center = attrs.get("center")
        if user and center is not None and not can_write_center(user, center):
            raise serializers.ValidationError(
                {"center": "You are not approved to work at this center."}
            )

        # The center field is only editable by ADMIN in the frontend form
        # (disabled otherwise) -- every other role relies on a client-side
        # is_default auto-fill that silently fails for them because the
        # /centers/ list endpoint is admin-only (403), leaving the field
        # blank. Fill it in server-side on create only, and only for
        # non-admins (who can never deliberately choose "no center" since
        # the field is disabled for them) -- never on update, so an existing
        # patient an admin deliberately left centerless (NULL = visible to
        # all staff, see CLAUDE.md) doesn't get silently bound on the next
        # unrelated PATCH by a non-admin.
        if (
            self.instance is None
            and attrs.get("center") is None
            and getattr(user, "role", None) != "ADMIN"
        ):
            attrs["center"] = MedicalCenter.objects.filter(is_default=True).first()

        # Cedula/guardian requiredness is only re-checked when the request is
        # a create or actually touches one of the relevant fields -- otherwise
        # a PATCH to an unrelated field (e.g. "phone") would re-run this
        # against a blank cedula/guardian_* fallback and permanently lock out
        # any existing minor whose cedula/guardian info isn't on file yet
        # (e.g. every minor already in the seeded dev data). Same pattern as
        # the ars_program check above, which only fires when ars_program is
        # actually present in attrs.
        if self.instance is None or any(k in attrs for k in _GUARDIAN_TRIGGER_KEYS):
            birth_date = attrs.get(
                "birth_date", self.instance.birth_date if self.instance else None
            )
            has_guardian = attrs.get(
                "has_guardian", self.instance.has_guardian if self.instance else True
            )
            age = patient_age(birth_date)
            is_minor = age is not None and age < 18
            errors = {}

            # Adults always need a cedula; minors only need their own cedula
            # when there's no guardian on file to identify them instead.
            cedula = attrs.get("cedula", self.instance.cedula if self.instance else "")
            if (not is_minor or not has_guardian) and not cedula:
                errors["cedula"] = "Cedula is required."

            if is_minor and has_guardian:
                guardians = attrs.get(
                    "guardians",
                    None if self.instance is None else list(self.instance.guardians.all()),
                )
                if not guardians:
                    errors["guardians"] = "At least one guardian is required when the patient is a minor with a guardian on file."
                else:
                    for g in guardians:
                        g_first = g.get("first_name") if isinstance(g, dict) else g.first_name
                        g_last = g.get("last_name") if isinstance(g, dict) else g.last_name
                        g_cedula = g.get("cedula") if isinstance(g, dict) else g.cedula
                        g_phone = g.get("phone") if isinstance(g, dict) else g.phone
                        if not (g_first and g_last and g_cedula and g_phone):
                            errors["guardians"] = (
                                "Each guardian requires first name, last name, cedula, and phone."
                            )
                            break

            if errors:
                raise serializers.ValidationError(errors)
        return attrs

    def to_representation(self, instance):
        data = super().to_representation(instance)
        return apply_masking(
            data,
            self._request_user(),
            masked_fields=(
                "phone",
                "address",
                "email",
                "cedula",
                "nss",
                "allergies",
                "critical_conditions",
                "first_name",
                "last_name",
                "full_name",
                "birth_date",
            ),
            masked_nulls=("age",),
            masked_list=(
                ("extra_phones", ("phone",)),
                ("guardians", ("first_name", "last_name", "cedula", "nss", "phone")),
            ),
        )
