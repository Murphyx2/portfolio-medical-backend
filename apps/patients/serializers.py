from datetime import date
import re
import unicodedata

from django.core.exceptions import ValidationError as DjangoValidationError
from django.core.validators import validate_email
from rest_framework import serializers

from apps.core.services import can_view_inactive, is_masked_role
from apps.core.validators import validate_phone
from apps.patients.models import Patient


def _mask(value: str) -> str:
    if not value:
        return value
    if len(value) <= 4:
        return "••••"
    return f"{value[:2]}••••{value[-2:]}"


class PatientSerializer(serializers.ModelSerializer):
    full_name = serializers.ReadOnlyField()
    age = serializers.SerializerMethodField()
    ars_name = serializers.CharField(source="ars.name", read_only=True, default=None)
    ars_program_name = serializers.CharField(
        source="ars_program.name", read_only=True, default=None
    )
    center_name = serializers.CharField(source="center.name", read_only=True, default=None)

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
            "phone",
            "address",
            "email",
            "cedula",
            "nss",
            "ars",
            "ars_name",
            "ars_program",
            "ars_program_name",
            "active",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["created_at", "updated_at"]

    def get_fields(self):
        fields = super().get_fields()
        if self.instance is None:
            fields["cedula"].required = True
            fields["cedula"].allow_blank = False
        if not can_view_inactive(self._request_user()):
            fields["active"].read_only = True
        return fields

    def _request_user(self):
        request = self.context.get("request")
        return getattr(request, "user", None) if request else None

    def get_age(self, obj) -> int | None:
        if not obj.birth_date:
            return None
        bd = obj.birth_date
        if isinstance(bd, str):
            try:
                bd = date.fromisoformat(bd)
            except ValueError:
                return None
        today = date.today()
        return (
            today.year
            - bd.year
            - ((today.month, today.day) < (bd.month, bd.day))
        )

    def validate_cedula(self, value: str) -> str:
        if value:
            digits = re.sub(r"\D", "", value)
            if len(digits) != 11:
                raise serializers.ValidationError(
                    "Cedula must contain exactly 11 digits."
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
            return value
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
        # NFKC folds fullwidth/halfwidth forms into ASCII (e.g. "１２３" -> "123");
        # anything that does not fold to ASCII digits (letters, symbols, other
        # scripts) is rejected, and at most 11 digits are allowed.
        normalized = unicodedata.normalize("NFKC", str(value))
        if not normalized.isascii() or not normalized.isdigit():
            raise serializers.ValidationError("NSS must contain digits only.")
        if len(normalized) > 11:
            raise serializers.ValidationError("NSS must be at most 11 digits.")
        return normalized

    def validate(self, attrs):
        ars = attrs.get("ars")
        if ars is None and self.instance is not None:
            ars = self.instance.ars
        program = attrs.get("ars_program")
        if ars is not None and program is not None and program.ars_id != ars.id:
            raise serializers.ValidationError(
                {"ars_program": "The selected program does not belong to the selected ARS."}
            )

        request = self.context.get("request")
        user = getattr(request, "user", None) if request else None
        center = attrs.get("center")
        if user and getattr(user, "is_doctor", False) and center is not None:
            from apps.core.services import user_accessible_center_ids

            if center.id not in user_accessible_center_ids(user):
                raise serializers.ValidationError(
                    {"center": "You are not approved to work at this center."}
                )
        return attrs

    def to_representation(self, instance):
        data = super().to_representation(instance)
        request = self.context.get("request")
        user = getattr(request, "user", None) if request else None
        if user and user.is_authenticated and is_masked_role(user):
            # IT and center managers see redacted contact PII, identifiers,
            # and names/birth date.
            for field in ("phone", "address", "email", "cedula", "nss"):
                data[field] = _mask(data[field])
            data["first_name"] = _mask(data["first_name"])
            data["last_name"] = _mask(data["last_name"])
            data["full_name"] = _mask(data["full_name"])
            data["birth_date"] = _mask(data["birth_date"]) if data.get("birth_date") else data.get("birth_date")
            data["age"] = None
        return data
