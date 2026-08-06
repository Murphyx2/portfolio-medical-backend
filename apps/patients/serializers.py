from datetime import date
import re

from rest_framework import serializers

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
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["created_at", "updated_at"]

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

    def validate_nss(self, value: str) -> str:
        if value and not value.isdigit():
            raise serializers.ValidationError("NSS must contain digits only.")
        return value

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
        if user and user.is_authenticated and not (
            user.is_admin or user.is_doctor or user.is_nurse or user.is_receptionist
        ):
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
