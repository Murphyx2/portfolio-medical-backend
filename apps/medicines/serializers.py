from rest_framework import serializers

from apps.core.serializers import CoreModelSerializer
from apps.medicines.models import Medicine


class MedicineSerializer(CoreModelSerializer):
    class Meta:
        model = Medicine
        fields = [
            "id",
            "generic_name",
            "commercial_name",
            "concentration",
            "forma",
            "via_pred",
            "concentracion_valor",
            "concentracion_unidad",
            "concentracion_unidad_otro",
            "created_at",
            "active",
        ]
        read_only_fields = ["created_at"]
