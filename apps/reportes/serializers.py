from rest_framework import serializers

from apps.reportes.models import ReportDefinition, ReportPack


class ReportDefinitionSerializer(serializers.ModelSerializer):
    class Meta:
        model = ReportDefinition
        fields = [
            "id",
            "name",
            "category",
            "description",
            "engine_key",
            "active",
            "last_generated_at",
        ]
        read_only_fields = ["id", "last_generated_at"]


class ReportPackSerializer(serializers.ModelSerializer):
    class Meta:
        model = ReportPack
        fields = [
            "id",
            "name",
            "periodicity",
            "engine_key",
            "active",
            "last_generated_at",
        ]
        read_only_fields = ["id", "last_generated_at"]


class GenerateReportSerializer(serializers.Serializer):
    mes = serializers.RegexField(r"^\d{4}-(0[1-9]|1[0-2])$")
    ars = serializers.IntegerField(required=False, allow_null=True)
    programa = serializers.IntegerField(required=False, allow_null=True)
    centro = serializers.IntegerField(required=False, allow_null=True)


class GeneratePackSerializer(serializers.Serializer):
    mes = serializers.RegexField(r"^\d{4}-(0[1-9]|1[0-2])$")
    centro = serializers.IntegerField(required=False, allow_null=True)
