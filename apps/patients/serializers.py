from datetime import date

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
            "phone",
            "address",
            "email",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["created_at", "updated_at"]

    def get_age(self, obj) -> int | None:
        if not obj.birth_date:
            return None
        today = date.today()
        return (
            today.year
            - obj.birth_date.year
            - ((today.month, today.day) < (obj.birth_date.month, obj.birth_date.day))
        )

    def to_representation(self, instance):
        data = super().to_representation(instance)
        request = self.context.get("request")
        if request and getattr(request.user, "is_it", False):
            # Least privilege: IT maintains the system, not patient PII.
            for field in ("phone", "address", "email"):
                data[field] = _mask(data[field])
        return data
