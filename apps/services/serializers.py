from rest_framework import serializers

from apps.core.serializers import CoreModelSerializer
from apps.core.services import program_belongs_to_ars
from apps.services.models import Service, ServicePrice, ServiceType


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
        fields = ["id", "name", "requires_doctor", "active"]

    def to_internal_value(self, data):
        # Normalize name to uppercase before DRF's UniqueValidator runs (it
        # runs before validate_name, so uppercasing there would be too late
        # to catch a same-name-different-case duplicate) -- the model's own
        # save() override is a defense-in-depth backstop for direct ORM use.
        if hasattr(data, "get") and isinstance(data.get("name"), str):
            data = {**data, "name": data["name"].upper()}
        return super().to_internal_value(data)


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


class ServicePriceSerializer(CoreModelSerializer):
    service_name = serializers.CharField(source="service.name", read_only=True)
    ars_name = serializers.CharField(source="ars.name", read_only=True)
    ars_program_name = serializers.CharField(
        source="ars_program.name", read_only=True, default=None
    )

    class Meta:
        model = ServicePrice
        fields = [
            "id",
            "service",
            "service_name",
            "ars",
            "ars_name",
            "ars_program",
            "ars_program_name",
            "co_pago",
            "created_at",
            "active",
        ]
        read_only_fields = ["created_at"]

    def validate(self, attrs):
        service = attrs.get("service", getattr(self.instance, "service", None))
        ars = attrs.get("ars", getattr(self.instance, "ars", None))
        program = attrs.get("ars_program", getattr(self.instance, "ars_program", None))
        if not program_belongs_to_ars(ars, program):
            raise serializers.ValidationError(
                {"ars_program": "The selected program does not belong to the selected ARS."}
            )
        # DRF can't auto-derive a UniqueTogetherValidator from a *partial*
        # UniqueConstraint (one with a `condition`) -- without this check, a
        # duplicate (service, ars, ars_program) combo reaches the DB and
        # surfaces as a raw IntegrityError/500 instead of a clean 400.
        dupes = ServicePrice.all_objects.filter(service=service, ars=ars, ars_program=program)
        if self.instance is not None:
            dupes = dupes.exclude(pk=self.instance.pk)
        if dupes.exists():
            raise serializers.ValidationError(
                {"ars": "A price already exists for this Service/ARS/Program combination."}
            )
        return attrs
