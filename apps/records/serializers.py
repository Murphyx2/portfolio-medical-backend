from io import BytesIO

from PIL import Image
from rest_framework import serializers

from apps.core.masking import apply_masking
from apps.core.serializers import CoreModelSerializer, full_name_or_username
from apps.core.services import can_write_center, sign_media_token
from apps.patients.serializers import PatientSummarySerializer
from apps.records.models import ConsultationLog, MedicalRecord, RecordImage

ALLOWED_IMAGE_FORMATS = {"JPEG", "PNG", "GIF", "WEBP"}


def _validate_patient_scope(context, attrs, user, instance):
    """Doctors may only write records for patients not bound to other centers."""
    if not user or not getattr(user, "is_doctor", False):
        return
    patient = attrs.get("patient") or (instance.patient if instance else None)
    if patient is None:
        return
    if not can_write_center(user, patient.center):
        raise serializers.ValidationError(
            {"patient": "The patient is not in your accessible centers."}
        )


def _validate_center_scope(context, attrs):
    """Doctors may only write records/logs at a center they're approved for."""
    user = getattr(context.get("request"), "user", None)
    center = attrs.get("center")
    if user and center is not None and not can_write_center(user, center):
        raise serializers.ValidationError(
            {"center": "You are not approved to work at this center."}
        )


class PatientLiteSerializer(PatientSummarySerializer):
    # Masked subset (see MedicalRecordSerializer/ConsultationLogSerializer's
    # apply_masking(masked_nested=(("patient_info", (...)),)) below):
    # full_name, cedula, nss.
    class Meta(PatientSummarySerializer.Meta):
        fields = ["id", "full_name", "gender", "cedula", "nss"]


class RecordImageSerializer(CoreModelSerializer):
    image_url = serializers.SerializerMethodField()

    class Meta:
        model = RecordImage
        fields = ["id", "record", "image", "image_url", "caption", "uploaded_by", "active"]
        read_only_fields = ["id", "image_url", "uploaded_by"]

    def validate_image(self, value):
        if value is None:
            return value
        if value.size > 5 * 1024 * 1024:
            raise serializers.ValidationError("Image must be smaller than 5 MB.")
        ext = value.name.rsplit(".", 1)[-1].lower() if "." in value.name else ""
        if ext not in {"jpg", "jpeg", "png", "gif", "webp"}:
            raise serializers.ValidationError("Unsupported image format.")
        # Verify magic bytes / real image content, not just the extension.
        try:
            image = Image.open(BytesIO(value.read()))
            format_name = image.format
            image.verify()
        except Exception:
            raise serializers.ValidationError("File is not a valid image.")
        finally:
            value.seek(0)
        if format_name not in ALLOWED_IMAGE_FORMATS:
            raise serializers.ValidationError("Unsupported image format.")
        return value

    def validate(self, attrs):
        user = getattr(self.context.get("request"), "user", None)
        record = attrs.get("record")
        if user and getattr(user, "is_doctor", False) and record is not None:
            if not (can_write_center(user, record.center) or record.created_by_id == user.id):
                raise serializers.ValidationError(
                    {"record": "The record is not in your scope."}
                )
        return attrs

    def get_image_url(self, obj):
        if not obj.image:
            return None
        signed = f"{obj.image.url}?token={sign_media_token(obj.image.name)}"
        request = self.context.get("request")
        if request:
            return request.build_absolute_uri(signed)
        return signed


class MedicalRecordSerializer(CoreModelSerializer):
    patient_info = PatientLiteSerializer(source="patient", read_only=True)
    created_by_name = serializers.SerializerMethodField()
    center_name = serializers.CharField(source="center.name", read_only=True, default=None)
    images = RecordImageSerializer(many=True, read_only=True)

    class Meta:
        model = MedicalRecord
        fields = [
            "id",
            "patient",
            "patient_info",
            "created_by",
            "created_by_name",
            "center",
            "center_name",
            "title",
            "date",
            "diagnosis",
            "treatment",
            "medicine_and_doses",
            "notes",
            "images",
            "active",
        ]
        read_only_fields = ["id", "created_by", "date"]

    def get_created_by_name(self, obj):
        return full_name_or_username(obj.created_by)

    def validate(self, attrs):
        user = getattr(self.context.get("request"), "user", None)
        _validate_center_scope(self.context, attrs)
        _validate_patient_scope(self.context, attrs, user, self.instance)
        return attrs

    def to_representation(self, instance):
        data = super().to_representation(instance)
        return apply_masking(
            data,
            self._request_user(),
            clinical_fields=("diagnosis", "treatment", "medicine_and_doses", "notes"),
            masked_fields=("created_by_name",),
            masked_nested=(("patient_info", ("full_name", "cedula", "nss")),),
        )


class ConsultationLogSerializer(CoreModelSerializer):
    patient_info = PatientLiteSerializer(source="patient", read_only=True)
    doctor_name = serializers.SerializerMethodField()
    center_name = serializers.CharField(source="center.name", read_only=True, default=None)

    class Meta:
        model = ConsultationLog
        fields = [
            "id",
            "patient",
            "patient_info",
            "doctor",
            "doctor_name",
            "center",
            "center_name",
            "date",
            "subjective",
            "objective",
            "assessment",
            "plan",
            "notes",
            "active",
        ]
        read_only_fields = ["id", "doctor", "date"]

    def get_doctor_name(self, obj):
        return full_name_or_username(obj.doctor)

    def validate(self, attrs):
        user = getattr(self.context.get("request"), "user", None)
        _validate_center_scope(self.context, attrs)
        _validate_patient_scope(self.context, attrs, user, self.instance)
        return attrs

    def to_representation(self, instance):
        data = super().to_representation(instance)
        return apply_masking(
            data,
            self._request_user(),
            clinical_fields=("subjective", "objective", "assessment", "plan", "notes"),
            masked_fields=("doctor_name",),
            masked_nested=(("patient_info", ("full_name", "cedula", "nss")),),
        )
