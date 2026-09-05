from django.utils import timezone
from rest_framework import serializers

from apps.core.masking import apply_masking
from apps.core.serializers import CoreModelSerializer, full_name_or_username
from apps.core.services import is_own_doctor_relation, program_belongs_to_ars
from apps.encounters.models import Encounter, EncounterDiagnosis, EncounterService
from apps.patients.serializers import PatientSummarySerializer as _PatientSummaryBase
from apps.services.services import resolve_line_price


def _sync_related(manager, items, *, is_valid, build_fields):
    """Diff-upsert-then-delete-orphans, shared by EncounterSerializer's
    _set_diagnoses/_set_services: an item carrying an ``id`` that matches an
    existing row is updated in place (preserving created_at/pk/FK
    references); anything else is created fresh; any row not resubmitted is
    deleted. ``manager`` is a related manager already scoped to the parent
    encounter (e.g. ``encounter.diagnoses``), so lookups/creates through it
    are implicitly scoped without an explicit ``encounter=`` filter.

    ``build_fields(item, existing_obj)`` receives the pre-existing row (or
    None for a new one) so callers can make update-vs-create decisions --
    e.g. EncounterService's co_pago snapshot, which should only be
    (re)computed on create or when the line's own service changes.
    """
    keep_ids = []
    for item in items:
        if not is_valid(item):
            continue
        item_id = item.get("id")
        obj = manager.filter(pk=item_id).first() if item_id else None
        fields = build_fields(item, obj)
        if obj is not None:
            for attr, value in fields.items():
                setattr(obj, attr, value)
            obj.save()
        else:
            obj = manager.create(**fields)
        keep_ids.append(obj.pk)
    manager.exclude(pk__in=keep_ids).delete()


class PatientSummarySerializer(_PatientSummaryBase):
    # Masked subset (see EncounterSerializer's apply_masking(masked_nested=,
    # masked_nested_nulls=) below): full_name, cedula, allergies,
    # critical_conditions, guardian_cedula, and age nulled.
    class Meta(_PatientSummaryBase.Meta):
        fields = [
            "id",
            "full_name",
            "age",
            "gender",
            "cedula",
            "allergies",
            "critical_conditions",
            "ars",
            "ars_name",
            "ars_program",
            "has_guardian",
            "guardian_cedula",
        ]


class EncounterDiagnosisSerializer(serializers.ModelSerializer):
    id = serializers.IntegerField(required=False)

    class Meta:
        model = EncounterDiagnosis
        fields = ["id", "description", "is_primary"]


class EncounterServiceSerializer(CoreModelSerializer):
    id = serializers.IntegerField(required=False)
    service_name = serializers.CharField(source="service.name", read_only=True)
    doctor_name = serializers.CharField(
        source="doctor.full_name", read_only=True, default=None
    )
    room_name = serializers.CharField(source="room.name", read_only=True, default=None)

    class Meta:
        model = EncounterService
        fields = [
            "id",
            "service",
            "service_name",
            "doctor",
            "doctor_name",
            "room",
            "room_name",
            "quantity",
            "notes",
            "status",
            "ars_covered",
            "authorization_number",
        ]

    def validate_doctor(self, value):
        if value is None:
            return value
        user = self._request_user()
        if user and user.is_authenticated and not is_own_doctor_relation(user, value):
            raise serializers.ValidationError(
                "Doctors may only manage encounters for themselves."
            )
        return value

    def validate(self, attrs):
        # Never persist a stale authorization number for an uncovered
        # line -- don't trust the frontend to have cleared it.
        ars_covered = attrs.get("ars_covered", getattr(self.instance, "ars_covered", True))
        if not ars_covered:
            attrs["authorization_number"] = None

        service = attrs.get("service", getattr(self.instance, "service", None))
        doctor = attrs.get("doctor", getattr(self.instance, "doctor", None))
        if service is not None and service.type.requires_doctor and doctor is None:
            raise serializers.ValidationError(
                {"doctor": "A doctor is required for this service."}
            )
        return attrs


class EncounterSerializer(CoreModelSerializer):
    patient_info = PatientSummarySerializer(source="patient", read_only=True)
    center_name = serializers.CharField(source="center.name", read_only=True, default=None)
    service_type_name = serializers.CharField(source="service_type.name", read_only=True)
    ars_name = serializers.CharField(source="ars.name", read_only=True, default=None)
    ars_program_name = serializers.CharField(
        source="ars_program.name", read_only=True, default=None
    )
    created_by_name = serializers.SerializerMethodField()
    diagnoses = EncounterDiagnosisSerializer(many=True, required=False)
    services = EncounterServiceSerializer(many=True, required=False)

    class Meta:
        model = Encounter
        fields = [
            "id",
            "encounter_number",
            "service_type",
            "service_type_name",
            "patient",
            "patient_info",
            "referring_doctor_name",
            "center",
            "center_name",
            "status",
            "priority",
            "admitted_at",
            "completed_at",
            "chief_complaint",
            "cancel_reason",
            "ars",
            "ars_name",
            "ars_program",
            "ars_program_name",
            "diagnoses",
            "services",
            "created_by",
            "created_by_name",
            "created_at",
            "updated_at",
            "active",
        ]
        read_only_fields = [
            "id",
            "encounter_number",
            "status",
            "admitted_at",
            "completed_at",
            "cancel_reason",
            "created_by",
            "created_at",
            "updated_at",
        ]

    def get_created_by_name(self, obj):
        return full_name_or_username(obj.created_by)

    def validate(self, attrs):
        ars = attrs.get("ars")
        if ars is None and self.instance is not None:
            ars = self.instance.ars
        program = attrs.get("ars_program")
        if not program_belongs_to_ars(ars, program):
            raise serializers.ValidationError(
                {"ars_program": "The selected program does not belong to the selected ARS."}
            )

        services = attrs.get("services")
        if services is not None:
            if not any(item.get("service") for item in services):
                raise serializers.ValidationError(
                    {"services": "At least one service is required."}
                )
        elif self.instance is None:
            raise serializers.ValidationError(
                {"services": "At least one service is required."}
            )
        return attrs

    def create(self, validated_data):
        diagnoses = validated_data.pop("diagnoses", [])
        services = validated_data.pop("services", [])
        user = self._request_user()
        encounter = Encounter.objects.create(created_by=user, **validated_data)
        self._set_diagnoses(encounter, diagnoses)
        self._set_services(encounter, services)
        return encounter

    def update(self, instance, validated_data):
        diagnoses = validated_data.pop("diagnoses", None)
        services = validated_data.pop("services", None)
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()
        if diagnoses is not None:
            self._set_diagnoses(instance, diagnoses)
        if services is not None:
            self._set_services(instance, services)
        return instance

    @staticmethod
    def _set_diagnoses(encounter, diagnoses):
        _sync_related(
            encounter.diagnoses,
            diagnoses,
            is_valid=lambda item: bool((item.get("description") or "").strip()),
            build_fields=lambda item, obj: {
                "description": (item.get("description") or "").strip(),
                "is_primary": item.get("is_primary", False),
            },
        )

    @staticmethod
    def _set_services(encounter, services):
        def build_fields(item, obj):
            service = item.get("service")
            ars_covered = item.get("ars_covered", True)
            fields = {
                "service": service,
                "doctor": item.get("doctor"),
                "room": item.get("room"),
                "quantity": item.get("quantity", 1),
                "notes": item.get("notes", ""),
                "status": item.get("status", EncounterService.Status.PENDING),
                "ars_covered": ars_covered,
                "authorization_number": item.get("authorization_number") if ars_covered else None,
            }
            # co_pago is an immutable billing snapshot (see EncounterService.co_pago):
            # resolve it on create, and re-resolve only if this update swaps the
            # line's own service -- never in response to ars_covered or the parent
            # encounter's ars/ars_program changing on an existing line.
            if obj is None or service is not None and service.pk != obj.service_id:
                fields["co_pago"] = resolve_line_price(
                    service, ars_covered, encounter.ars, encounter.ars_program
                )
            return fields

        _sync_related(
            encounter.services,
            services,
            is_valid=lambda item: item.get("service") is not None,
            build_fields=build_fields,
        )

    def to_representation(self, instance):
        data = super().to_representation(instance)
        return apply_masking(
            data,
            self._request_user(),
            clinical_fields=("chief_complaint",),
            clinical_nested=(("diagnoses", ("description",)),),
            masked_fields=("created_by_name",),
            masked_nested=(
                (
                    "patient_info",
                    (
                        "full_name",
                        "cedula",
                        "allergies",
                        "critical_conditions",
                        "guardian_cedula",
                    ),
                ),
            ),
            masked_nested_nulls=(("patient_info", ("age",)),),
        )
