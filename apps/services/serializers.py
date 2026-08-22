from rest_framework import serializers

from apps.core.serializers import CoreModelSerializer
from apps.services.models import Service, ServiceType


class ServiceLiteSerializer(serializers.ModelSerializer):
    """Compact read-only representation for nesting inside other apps'
    serializers (e.g. DoctorProfileSerializer.services_detail) -- mirrors
    encounters' DoctorLiteSerializer pattern."""

    class Meta:
        model = Service
        fields = ["id", "name"]


class ServiceTypeSerializer(CoreModelSerializer):
    class Meta:
        model = ServiceType
        fields = ["id", "name", "requires_doctor", "requires_diagnosis", "active"]


class ServiceSerializer(CoreModelSerializer):
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
