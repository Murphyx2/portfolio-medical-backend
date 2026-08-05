from io import BytesIO

from PIL import Image
from rest_framework import serializers

from apps.centers.models import DoctorCenterBinding
from apps.patients.models import Patient
from apps.patients.serializers import _mask
from apps.records.models import ConsultationLog, MedicalRecord, RecordImage

ALLOWED_IMAGE_FORMATS = {"JPEG", "PNG", "GIF", "WEBP"}

CLINICAL_FIELDS = ["diagnosis", "treatment", "medicine_and_doses", "notes"]


class PatientLiteSerializer(serializers.ModelSerializer):
    full_name = serializers.ReadOnlyField()

    class Meta:
        model = Patient
        fields = ["id", "full_name", "gender"]


class RecordImageSerializer(serializers.ModelSerializer):
    image_url = serializers.SerializerMethodField()

    class Meta:
        model = RecordImage
        fields = ["id", "record", "image", "image_url", "caption", "uploaded_by"]
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

    def get_image_url(self, obj):
        request = self.context.get("request")
        if obj.image and request:
            return request.build_absolute_uri(obj.image.url)
        return obj.image.url if obj.image else None


class MedicalRecordSerializer(serializers.ModelSerializer):
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
        ]
        read_only_fields = ["id", "created_by", "date"]

    def get_created_by_name(self, obj):
        return obj.created_by.get_full_name() or obj.created_by.username

    def validate(self, attrs):
        user = getattr(getattr(self.context.get("request"), "user", None), "id", None)
        center = attrs.get("center")
        if user and center is not None:
            user_obj = self.context["request"].user
            if getattr(user_obj, "is_doctor", False) and not DoctorCenterBinding.objects.filter(
                doctor__user=user_obj, center=center, approved=True
            ).exists():
                raise serializers.ValidationError(
                    {"center": "You are not approved to work at this center."}
                )
        return attrs

    def to_representation(self, instance):
        data = super().to_representation(instance)
        request = self.context.get("request")
        user = getattr(request, "user", None) if request else None
        if user and not (user.is_doctor or user.is_nurse or user.is_admin):
            for field in CLINICAL_FIELDS:
                if data.get(field):
                    data[field] = _mask(str(data[field]))
        return data


class ConsultationLogSerializer(serializers.ModelSerializer):
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
        ]
        read_only_fields = ["id", "doctor", "date"]

    def get_doctor_name(self, obj):
        return obj.doctor.get_full_name() or obj.doctor.username

    def validate(self, attrs):
        user = getattr(getattr(self.context.get("request"), "user", None), "id", None)
        center = attrs.get("center")
        if user and center is not None:
            user_obj = self.context["request"].user
            if getattr(user_obj, "is_doctor", False) and not DoctorCenterBinding.objects.filter(
                doctor__user=user_obj, center=center, approved=True
            ).exists():
                raise serializers.ValidationError(
                    {"center": "You are not approved to work at this center."}
                )
        return attrs

    def to_representation(self, instance):
        data = super().to_representation(instance)
        request = self.context.get("request")
        user = getattr(request, "user", None) if request else None
        if user and not (user.is_doctor or user.is_nurse or user.is_admin):
            for field in ("subjective", "objective", "assessment", "plan", "notes"):
                if data.get(field):
                    data[field] = _mask(str(data[field]))
        return data
