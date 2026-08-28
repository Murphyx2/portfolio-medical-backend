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
        fields = ["id", "record", "image", "image_url", "caption", "uploaded_by", "active", "created_at"]
        read_only_fields = ["id", "image_url", "uploaded_by", "created_at"]

    def get_fields(self):
        fields = super().get_fields()
        # This is the app's only multipart/form-data endpoint (it carries the
        # file). DRF's BooleanField treats a key missing from HTML-style form
        # data as an unchecked checkbox -> False, not "apply the model
        # default" -- unlike a JSON POST, where a missing key just uses the
        # default. CoreModelSerializer's admin-writable `active` exists for
        # soft-delete/restore via PATCH on an existing row; on create it was
        # silently flipping every upload to active=False for any role that
        # can_view_inactive (ADMIN/CENTER_MANAGER), since the frontend never
        # sends an `active` field when uploading. Force it read-only on
        # create only, so a new image always gets the real model default.
        if self.instance is None and "active" in fields:
            fields["active"].read_only = True
        return fields

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
        # Relative, not request.build_absolute_uri(): behind the Vite dev
        # proxy (changeOrigin: true, PROXY_TARGET=http://backend:8000) Django
        # sees Host: backend:8000 -- an absolute URL would bake in that
        # Docker-internal hostname, which the browser can't resolve. A
        # relative URL resolves against the page's own origin and rides the
        # existing /media proxy, same as /api calls already do.
        return f"{obj.image.url}?token={sign_media_token(obj.image.name)}"


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
            "habits_snapshot",
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
            "last_fr_at", "last_glucose", "last_glucose_at", "habits_snapshot",
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
            "habits", "habits_notes",
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

    def validate_habits(self, value):
        if not isinstance(value, dict):
            raise serializers.ValidationError("Habits must be an object.")
        allowed_keys = {
            "tabaco", "alcohol", "cafe", "vapeo", "psicoactivas",
            "actividad_fisica", "sueno", "patron_alimentario", "otros",
        }
        unknown = set(value.keys()) - allowed_keys
        if unknown:
            raise serializers.ValidationError(f"Unknown habit key(s): {', '.join(sorted(unknown))}.")

        substance_statuses = {"no_registrado", "nunca", "ex", "ocasional", "activo"}
        status_enums = {
            "tabaco": substance_statuses,
            "alcohol": substance_statuses,
            "cafe": substance_statuses,
            "vapeo": substance_statuses,
            "psicoactivas": substance_statuses,
            "actividad_fisica": {"no_registrado", "sedentario", "insuficiente", "adecuado", "intenso"},
            "sueno": {"no_registrado", "reparador", "irregular", "insomnio"},
        }
        for key, enum in status_enums.items():
            entry = value.get(key)
            if entry is None:
                continue
            if not isinstance(entry, dict):
                raise serializers.ValidationError(f"'{key}' must be an object.")
            status = entry.get("status")
            if status is not None and status not in enum:
                raise serializers.ValidationError(f"Invalid status '{status}' for '{key}'.")

        diet = value.get("patron_alimentario")
        if diet is not None:
            if not isinstance(diet, dict) or not isinstance(diet.get("tags", []), list):
                raise serializers.ValidationError("'patron_alimentario.tags' must be a list.")
            if not all(isinstance(t, str) for t in diet.get("tags", [])):
                raise serializers.ValidationError("'patron_alimentario.tags' must be strings.")

        otros = value.get("otros")
        if otros is not None:
            if not isinstance(otros, list):
                raise serializers.ValidationError("'otros' must be a list.")
            for item in otros:
                if not isinstance(item, dict) or not isinstance(item.get("name", ""), str):
                    raise serializers.ValidationError("Each 'otros' entry needs a string 'name'.")
                if len(item.get("name", "")) > 80:
                    raise serializers.ValidationError("'otros' name must be 80 characters or fewer.")
                if len(item.get("note", "") or "") > 1000:
                    raise serializers.ValidationError("'otros' note must be 1000 characters or fewer.")
        return value

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
            clinical_fields=("dx", "tx", "observaciones", "habits_notes"),
            masked_fields=("author_name",),
            masked_nulls=("habits",),
        )


def _validate_range(value, low, high, label):
    if value is None:
        return value
    if not (low <= value <= high):
        raise serializers.ValidationError(f"{label} debe estar entre {low} y {high}.")
    return value
