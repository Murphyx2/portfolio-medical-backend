from rest_framework import serializers

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
        ]
        read_only_fields = ["created_at"]
