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
        # Medicine.unique_together (generic_name, commercial_name,
        # concentration) makes DRF force `concentration` required by
        # default, even though the model field itself is blank=True and
        # Medicine.save() keeps it in sync from concentracion_valor/
        # concentracion_unidad -- the catalogs UI no longer sends this
        # legacy field at all, so it must stay optional here too (with a
        # default so UniqueTogetherValidator has something to compare).
        extra_kwargs = {"concentration": {"required": False, "default": ""}}
