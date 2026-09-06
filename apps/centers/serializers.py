from rest_framework import serializers

from apps.centers.models import (
    DoctorCenterBinding,
    MedicalCenter,
    MedicalCenterEmail,
    MedicalCenterPhone,
)
from apps.core.serializers import CoreModelSerializer
from apps.core.validators import validate_phone


class MedicalCenterPhoneSerializer(serializers.ModelSerializer):
    class Meta:
        model = MedicalCenterPhone
        fields = ["id", "number"]

    def validate_number(self, value: str) -> str:
        return validate_phone(value)


class MedicalCenterEmailSerializer(serializers.ModelSerializer):
    class Meta:
        model = MedicalCenterEmail
        fields = ["id", "email"]


class MedicalCenterSerializer(CoreModelSerializer):
    doctor_count = serializers.IntegerField(read_only=True)
    # Repeatable phones/emails beyond the legacy phone/email fields -- write
    # side replaces the full set on every save (delete-and-recreate),
    # mirroring DoctorProfileSerializer.extra_phones.
    phones = MedicalCenterPhoneSerializer(many=True, required=False)
    emails = MedicalCenterEmailSerializer(many=True, required=False)

    class Meta:
        model = MedicalCenter
        fields = [
            "id",
            "name",
            "code",
            "address",
            "phone",
            "email",
            "rnc",
            "nombre_legal",
            "nombre_corto",
            "logo",
            "phones",
            "emails",
            "is_default",
            "doctor_count",
            "active",
        ]

    def validate_phone(self, value: str) -> str:
        return validate_phone(value)

    def create(self, validated_data):
        phones = validated_data.pop("phones", None)
        emails = validated_data.pop("emails", None)
        center = super().create(validated_data)
        if phones:
            MedicalCenterPhone.objects.bulk_create(
                MedicalCenterPhone(center=center, number=p["number"], order=i)
                for i, p in enumerate(phones)
            )
        if emails:
            MedicalCenterEmail.objects.bulk_create(
                MedicalCenterEmail(center=center, email=e["email"], order=i)
                for i, e in enumerate(emails)
            )
        return center

    def update(self, instance, validated_data):
        phones = validated_data.pop("phones", None)
        emails = validated_data.pop("emails", None)
        center = super().update(instance, validated_data)
        if phones is not None:
            center.phones.all().delete()
            MedicalCenterPhone.objects.bulk_create(
                MedicalCenterPhone(center=center, number=p["number"], order=i)
                for i, p in enumerate(phones)
            )
        if emails is not None:
            center.emails.all().delete()
            MedicalCenterEmail.objects.bulk_create(
                MedicalCenterEmail(center=center, email=e["email"], order=i)
                for i, e in enumerate(emails)
            )
        return center




class DoctorCenterBindingSerializer(CoreModelSerializer):
    doctor_full_name = serializers.CharField(source="doctor.full_name", read_only=True)
    center_name = serializers.CharField(source="center.name", read_only=True)

    class Meta:
        model = DoctorCenterBinding
        fields = [
            "id",
            "doctor",
            "doctor_full_name",
            "center",
            "center_name",
            "approved",
            "approved_by",
            "created_at",
            "active",
        ]
        read_only_fields = ["approved_by"]
