from io import BytesIO

from PIL import Image
from rest_framework import serializers
from rest_framework.validators import UniqueValidator

from apps.core.masking import apply_masking
from apps.core.serializers import CoreModelSerializer, full_name_or_username
from apps.core.services import sign_media_token
from apps.patients.serializers import PatientGuardianSerializer, PatientSummarySerializer
from apps.records.models import (
    APCategory,
    APType,
    MedicalRecord,
    RecordEntry,
    RecordFamilyCondition,
    RecordImage,
    RecordPersonalCondition,
)

ALLOWED_IMAGE_FORMATS = {"JPEG", "PNG", "GIF", "WEBP"}


class PatientLiteSerializer(PatientSummarySerializer):
    # Masked subset (see MedicalRecordSerializer/RecordEntrySerializer's
    # apply_masking(masked_nested=(("patient_info", (...)),)) below):
    # full_name, cedula, nss, plus the snapshot-header fields (birth_date,
    # guardians) the Expediente modal's read-only header needs.
    guardians = PatientGuardianSerializer(many=True, read_only=True)

    class Meta(PatientSummarySerializer.Meta):
        fields = ["id", "full_name", "gender", "cedula", "nss", "birth_date", "has_guardian", "guardians"]


class APCategorySerializer(CoreModelSerializer):
    # Explicit UniqueValidator with a clean Spanish message -- DRF's
    # auto-generated one for this field resolves to the oddly-capitalized,
    # untranslated "ap category with this name already exists." (derived
    # from Django's camel_case_to_spaces("APCategory")).
    name = serializers.CharField(
        max_length=255,
        validators=[
            # all_objects, not objects: the DB-level unique=True on name
            # applies regardless of active/soft-deleted status, so a
            # soft-deleted category still blocks the name -- the active-only
            # manager would miss that row and let a raw IntegrityError (500)
            # through instead of this clean validation error.
            UniqueValidator(
                queryset=APCategory.all_objects.all(),
                message="Ya existe una categoría con este nombre.",
            )
        ],
    )

    class Meta:
        model = APCategory
        fields = ["id", "name", "sort_order", "active"]


class APTypeSerializer(CoreModelSerializer):
    category_name = serializers.CharField(source="category.name", read_only=True)

    class Meta:
        model = APType
        fields = ["id", "category", "category_name", "name", "sort_order", "active"]


class RecordImageSerializer(CoreModelSerializer):
    image_url = serializers.SerializerMethodField()

    class Meta:
        model = RecordImage
        fields = ["id", "record", "image", "image_url", "caption", "uploaded_by", "active"]
        read_only_fields = ["id", "image_url", "uploaded_by"]

    def validate_image(self, value):
        if value is None:
            return value
        from apps.systemsettings.services import get_settings

        max_mb = get_settings().max_image_upload_mb
        if value.size > max_mb * 1024 * 1024:
            raise serializers.ValidationError(f"Image must be smaller than {max_mb} MB.")
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
        if not obj.image:
            return None
        signed = f"{obj.image.url}?token={sign_media_token(obj.image.name)}"
        request = self.context.get("request")
        if request:
            return request.build_absolute_uri(signed)
        return signed


class RecordPersonalConditionSerializer(CoreModelSerializer):
    label = serializers.SerializerMethodField()

    class Meta:
        model = RecordPersonalCondition
        fields = ["id", "record", "ap_type", "custom_label", "is_custom", "label"]

    def get_label(self, obj):
        return obj.ap_type.name if obj.ap_type_id else obj.custom_label

    def validate(self, attrs):
        ap_type = attrs.get("ap_type", getattr(self.instance, "ap_type", None))
        custom_label = attrs.get("custom_label", getattr(self.instance, "custom_label", ""))
        if bool(ap_type) == bool(custom_label):
            raise serializers.ValidationError(
                "Provide exactly one of ap_type or custom_label."
            )
        attrs["is_custom"] = not bool(ap_type)
        return attrs


class RecordFamilyConditionSerializer(CoreModelSerializer):
    label = serializers.SerializerMethodField()

    class Meta:
        model = RecordFamilyCondition
        fields = [
            "id", "record", "related_patient", "relationship", "relationship_other",
            "relative_name", "ap_type", "custom_label", "is_custom", "label",
        ]

    def get_label(self, obj):
        return obj.ap_type.name if obj.ap_type_id else obj.custom_label

    def validate(self, attrs):
        ap_type = attrs.get("ap_type", getattr(self.instance, "ap_type", None))
        custom_label = attrs.get("custom_label", getattr(self.instance, "custom_label", ""))
        if bool(ap_type) == bool(custom_label):
            raise serializers.ValidationError(
                "Provide exactly one of ap_type or custom_label."
            )
        attrs["is_custom"] = not bool(ap_type)
        relationship = attrs.get("relationship", getattr(self.instance, "relationship", ""))
        relationship_other = attrs.get(
            "relationship_other", getattr(self.instance, "relationship_other", "")
        )
        if relationship == RecordFamilyCondition.Relationship.OTRO and not relationship_other:
            raise serializers.ValidationError(
                {"relationship_other": "Required when relationship is Otro."}
            )
        return attrs


class MedicalRecordSerializer(CoreModelSerializer):
    patient_info = PatientLiteSerializer(source="patient", read_only=True)
    created_by_name = serializers.SerializerMethodField()
    center_name = serializers.CharField(source="center.name", read_only=True, default=None)
    images = RecordImageSerializer(many=True, read_only=True)
    personal_conditions = RecordPersonalConditionSerializer(many=True, read_only=True)
    family_conditions = RecordFamilyConditionSerializer(many=True, read_only=True)

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
            "last_visit_at",
            "last_height_cm", "last_height_at",
            "last_weight_lb", "last_weight_at",
            "last_imc", "last_imc_at",
            "last_ta_systolic", "last_ta_diastolic", "last_ta_at",
            "last_fc", "last_fc_at",
            "last_fr", "last_fr_at",
            "last_glucose", "last_glucose_at",
            "images",
            "personal_conditions",
            "family_conditions",
            "active",
        ]
        read_only_fields = [
            "id", "created_by",
            "last_visit_at", "last_height_cm", "last_height_at", "last_weight_lb",
            "last_weight_at", "last_imc", "last_imc_at", "last_ta_systolic",
            "last_ta_diastolic", "last_ta_at", "last_fc", "last_fc_at", "last_fr",
            "last_fr_at", "last_glucose", "last_glucose_at",
        ]

    def get_created_by_name(self, obj):
        return full_name_or_username(obj.created_by)

    def to_representation(self, instance):
        data = super().to_representation(instance)
        return apply_masking(
            data,
            self._request_user(),
            masked_fields=("created_by_name",),
            masked_nested=(("patient_info", ("full_name", "cedula", "nss", "birth_date")),),
        )


class RecordEntrySerializer(CoreModelSerializer):
    author_name = serializers.SerializerMethodField()

    class Meta:
        model = RecordEntry
        fields = [
            "id", "record", "author", "author_name", "status",
            "ta_systolic", "ta_diastolic", "fc", "fr", "weight_lb", "height_cm",
            "talla_cm", "temperature_c", "glucose", "vitals_notes", "imc",
            "dx", "tx", "observaciones",
            "personal_ap_snapshot", "family_ap_snapshot", "completed_at",
            "created_at", "updated_at",
        ]
        read_only_fields = [
            "id", "author", "status", "imc", "personal_ap_snapshot",
            "family_ap_snapshot", "completed_at", "created_at", "updated_at",
        ]

    def get_author_name(self, obj):
        return full_name_or_username(obj.author)

    def validate_ta_systolic(self, value):
        return _validate_range(value, 1, 300, "TA sistólica")

    def validate_ta_diastolic(self, value):
        return _validate_range(value, 1, 300, "TA diastólica")

    def validate_fc(self, value):
        return _validate_range(value, 1, 300, "FC")

    def validate_fr(self, value):
        return _validate_range(value, 1, 120, "FR")

    def validate_weight_lb(self, value):
        return _validate_range(value, 0.1, 1000, "Peso")

    def validate_height_cm(self, value):
        return _validate_range(value, 20, 250, "Estatura")

    def validate_talla_cm(self, value):
        return _validate_range(value, 20, 250, "Talla")

    def validate_temperature_c(self, value):
        return _validate_range(value, 30.0, 45.0, "Temperatura")

    def validate_glucose(self, value):
        return _validate_range(value, 20, 1000, "Glucosa")

    def validate(self, attrs):
        systolic = attrs.get("ta_systolic", getattr(self.instance, "ta_systolic", None))
        diastolic = attrs.get("ta_diastolic", getattr(self.instance, "ta_diastolic", None))
        if bool(systolic) != bool(diastolic):
            raise serializers.ValidationError(
                "TA requires both systolic and diastolic, or neither."
            )
        if systolic and diastolic and systolic < diastolic:
            raise serializers.ValidationError(
                {"ta_systolic": "Systolic must be greater than or equal to diastolic."}
            )
        return attrs

    def to_representation(self, instance):
        data = super().to_representation(instance)
        return apply_masking(
            data,
            self._request_user(),
            clinical_fields=("dx", "tx", "observaciones"),
            masked_fields=("author_name",),
        )


def _validate_range(value, low, high, label):
    if value is None:
        return value
    if not (low <= value <= high):
        raise serializers.ValidationError(f"{label} debe estar entre {low} y {high}.")
    return value
