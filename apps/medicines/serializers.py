from rest_framework import serializers

from apps.core.services import can_view_inactive
from apps.medicines.models import Medicine


class MedicineSerializer(serializers.ModelSerializer):
    class Meta:
        model = Medicine
        fields = [
            "id",
            "generic_name",
            "commercial_name",
            "concentration",
            "created_at",
            "active",
        ]
        read_only_fields = ["created_at"]

    def get_fields(self):
        fields = super().get_fields()
        request = self.context.get("request")
        user = getattr(request, "user", None) if request else None
        if not can_view_inactive(user):
            fields["active"].read_only = True
        return fields
