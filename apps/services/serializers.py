from rest_framework import serializers

from apps.core.services import can_view_inactive
from apps.services.models import Service, ServiceType


class ServiceTypeSerializer(serializers.ModelSerializer):
    class Meta:
        model = ServiceType
        fields = ["id", "name", "requires_doctor", "requires_diagnosis", "active"]

    def get_fields(self):
        fields = super().get_fields()
        request = self.context.get("request")
        user = getattr(request, "user", None) if request else None
        if not can_view_inactive(user):
            fields["active"].read_only = True
        return fields


class ServiceSerializer(serializers.ModelSerializer):
    type_name = serializers.CharField(source="type.name", read_only=True)

    class Meta:
        model = Service
        fields = [
            "id",
            "simon",
            "name",
            "type",
            "type_name",
            "co_pago",
            "privado",
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
