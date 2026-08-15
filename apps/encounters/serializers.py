from django.utils import timezone
from rest_framework import serializers

from apps.core.services import can_view_inactive, is_masked_role
from apps.doctors.models import DoctorProfile
from apps.encounters.models import Encounter, EncounterDiagnosis, EncounterService
from apps.patients.filters import patient_age
from apps.patients.models import Patient
from apps.patients.serializers import _mask

# Free-text clinical fields masked for anyone who isn't a doctor/nurse/admin
# -- same convention as apps.records.serializers.CLINICAL_FIELDS, so a
# receptionist/center-manager can still administer the encounter (dates,
# room, coverage, status) without seeing clinical narrative text.
CLINICAL_FIELDS = ["chief_complaint"]


def _request_user(context):
    request = context.get("request")
    return getattr(request, "user", None) if request else None


class PatientSummarySerializer(serializers.ModelSerializer):
    full_name = serializers.ReadOnlyField()
    age = serializers.SerializerMethodField()
    ars_name = serializers.CharField(source="ars.name", read_only=True, default=None)

    class Meta:
        model = Patient
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

    def get_age(self, obj) -> int | None:
        return patient_age(obj)


class DoctorLiteSerializer(serializers.ModelSerializer):
    full_name = serializers.ReadOnlyField()

    class Meta:
        model = DoctorProfile
        fields = ["id", "code", "full_name", "specialty"]


class EncounterDiagnosisSerializer(serializers.ModelSerializer):
    id = serializers.IntegerField(required=False)

    class Meta:
        model = EncounterDiagnosis
        fields = ["id", "description", "is_primary"]


class EncounterServiceSerializer(serializers.ModelSerializer):
    id = serializers.IntegerField(required=False)
    service_name = serializers.CharField(source="service.name", read_only=True)
    doctor_name = serializers.CharField(
        source="doctor.full_name", read_only=True, default=None
    )

    class Meta:
        model = EncounterService
        fields = [
            "id",
            "service",
            "service_name",
            "doctor",
            "doctor_name",
            "quantity",
            "notes",
            "status",
        ]


class EncounterSerializer(serializers.ModelSerializer):
    patient_info = PatientSummarySerializer(source="patient", read_only=True)
    doctor_info = DoctorLiteSerializer(source="doctor", read_only=True)
    room_name = serializers.CharField(source="room.name", read_only=True, default=None)
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
            "doctor",
            "doctor_info",
            "referring_doctor_name",
            "room",
            "room_name",
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
            "authorization_number",
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

    def get_fields(self):
        fields = super().get_fields()
        if not can_view_inactive(_request_user(self.context)):
            fields["active"].read_only = True
        return fields

    def get_created_by_name(self, obj):
        return obj.created_by.get_full_name() or obj.created_by.username

    def validate_doctor(self, value):
        if value is None:
            return value
        user = _request_user(self.context)
        if user and user.is_authenticated and getattr(user, "is_doctor", False):
            if not hasattr(user, "doctor_profile") or value.id != user.doctor_profile.id:
                raise serializers.ValidationError(
                    "Doctors may only manage encounters for themselves."
                )
        return value

    def validate(self, attrs):
        ars = attrs.get("ars")
        if ars is None and self.instance is not None:
            ars = self.instance.ars
        program = attrs.get("ars_program")
        if ars is not None and program is not None and program.ars_id != ars.id:
            raise serializers.ValidationError(
                {"ars_program": "The selected program does not belong to the selected ARS."}
            )

        service_type = attrs.get(
            "service_type", self.instance.service_type if self.instance else None
        )
        doctor = attrs.get("doctor", self.instance.doctor if self.instance else None)
        if service_type is not None and service_type.requires_doctor and doctor is None:
            raise serializers.ValidationError(
                {"doctor": "A doctor is required for this service type."}
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
        user = _request_user(self.context)
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
        keep_ids = []
        for item in diagnoses:
            description = (item.get("description") or "").strip()
            if not description:
                continue
            diagnosis_id = item.get("id")
            if diagnosis_id:
                diagnosis = EncounterDiagnosis.objects.filter(
                    pk=diagnosis_id, encounter=encounter
                ).first()
                if diagnosis is not None:
                    diagnosis.description = description
                    diagnosis.is_primary = item.get("is_primary", False)
                    diagnosis.save()
                    keep_ids.append(diagnosis.pk)
                    continue
            keep_ids.append(
                EncounterDiagnosis.objects.create(
                    encounter=encounter,
                    description=description,
                    is_primary=item.get("is_primary", False),
                ).pk
            )
        encounter.diagnoses.exclude(pk__in=keep_ids).delete()

    @staticmethod
    def _set_services(encounter, services):
        keep_ids = []
        for item in services:
            service = item.get("service")
            if service is None:
                continue
            service_id = item.get("id")
            fields = {
                "service": service,
                "doctor": item.get("doctor"),
                "quantity": item.get("quantity", 1),
                "notes": item.get("notes", ""),
                "status": item.get("status", EncounterService.Status.PENDING),
            }
            if service_id:
                line = EncounterService.objects.filter(
                    pk=service_id, encounter=encounter
                ).first()
                if line is not None:
                    for attr, value in fields.items():
                        setattr(line, attr, value)
                    line.save()
                    keep_ids.append(line.pk)
                    continue
            keep_ids.append(EncounterService.objects.create(encounter=encounter, **fields).pk)
        encounter.services.exclude(pk__in=keep_ids).delete()

    def to_representation(self, instance):
        data = super().to_representation(instance)
        user = _request_user(self.context)
        if user and not (
            getattr(user, "is_doctor", False)
            or getattr(user, "is_nurse", False)
            or getattr(user, "is_admin", False)
        ):
            for field in CLINICAL_FIELDS:
                if data.get(field):
                    data[field] = _mask(str(data[field]))
            for diagnosis in data.get("diagnoses") or []:
                if diagnosis.get("description"):
                    diagnosis["description"] = _mask(str(diagnosis["description"]))
        if user and is_masked_role(user):
            patient_info = data.get("patient_info")
            if patient_info:
                for field in (
                    "full_name",
                    "cedula",
                    "allergies",
                    "critical_conditions",
                    "guardian_cedula",
                ):
                    if patient_info.get(field):
                        patient_info[field] = _mask(str(patient_info[field]))
                patient_info["age"] = None
            if data.get("created_by_name"):
                data["created_by_name"] = _mask(str(data["created_by_name"]))
        return data
