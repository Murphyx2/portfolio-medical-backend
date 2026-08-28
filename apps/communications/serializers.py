from django.urls import reverse
from rest_framework import serializers

from apps.accounts.models import User
from apps.communications.models import CommunicationsSettings, Delivery, Message, Template
from apps.core.serializers import CoreModelSerializer, full_name_or_username


class CommunicationsSettingsSerializer(serializers.ModelSerializer):
    whatsapp_access_token = serializers.CharField(
        write_only=True, required=False, allow_blank=True
    )
    whatsapp_app_secret = serializers.CharField(
        write_only=True, required=False, allow_blank=True
    )
    whatsapp_access_token_last4 = serializers.SerializerMethodField()
    whatsapp_app_secret_last4 = serializers.SerializerMethodField()
    whatsapp_configured = serializers.SerializerMethodField()
    webhook_url = serializers.SerializerMethodField()

    class Meta:
        model = CommunicationsSettings
        fields = [
            "id",
            "from_name",
            "reply_to",
            "whatsapp_phone_number_id",
            "whatsapp_business_account_id",
            "whatsapp_access_token",
            "whatsapp_access_token_last4",
            "whatsapp_app_secret",
            "whatsapp_app_secret_last4",
            "whatsapp_verify_token",
            "whatsapp_default_country_code",
            "whatsapp_reminder_hours",
            "whatsapp_master_enabled",
            "whatsapp_configured",
            "webhook_url",
            "updated_at",
        ]
        read_only_fields = ["id", "updated_at"]

    def _last4(self, value: str) -> str:
        return value[-4:] if value else ""

    def get_whatsapp_access_token_last4(self, obj) -> str:
        return self._last4(obj.whatsapp_access_token)

    def get_whatsapp_app_secret_last4(self, obj) -> str:
        return self._last4(obj.whatsapp_app_secret)

    def get_whatsapp_configured(self, obj) -> bool:
        return obj.whatsapp_configured()

    def get_webhook_url(self, obj) -> str:
        request = self.context.get("request")
        path = reverse("communications-whatsapp-webhook")
        return request.build_absolute_uri(path) if request else path

    def update(self, instance, validated_data):
        # An empty/omitted secret on a follow-up PATCH must never wipe an
        # already-saved one -- the client only ever sends a real value when
        # the admin explicitly clicks "Cambiar token".
        for field in ("whatsapp_access_token", "whatsapp_app_secret"):
            if not validated_data.get(field):
                validated_data.pop(field, None)
        return super().update(instance, validated_data)


class TemplateSerializer(CoreModelSerializer):
    class Meta:
        model = Template
        fields = [
            "id",
            "channel",
            "kind",
            "provider_name",
            "language",
            "body_email",
            "variables_json",
            "is_active",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]


class RecipientSpecSerializer(serializers.Serializer):
    """Write-only recipient selection for a staff-email compose payload."""

    all_staff = serializers.BooleanField(default=False)
    roles = serializers.ListField(
        child=serializers.ChoiceField(choices=User.Role.choices), required=False, default=list
    )
    user_ids = serializers.ListField(
        child=serializers.IntegerField(), required=False, default=list
    )


class MessageSerializer(CoreModelSerializer):
    created_by_name = serializers.SerializerMethodField()
    recipients = RecipientSpecSerializer(write_only=True, required=False)

    class Meta:
        model = Message
        fields = [
            "id",
            "channel",
            "audience",
            "kind",
            "priority",
            "subject",
            "body",
            "template",
            "created_by",
            "created_by_name",
            "scheduled_for",
            "status",
            "recipient_count",
            "appointment",
            "recipients",
            "created_at",
        ]
        read_only_fields = ["id", "created_by", "recipient_count", "appointment", "created_at"]

    def get_created_by_name(self, obj) -> str:
        return full_name_or_username(obj.created_by) if obj.created_by else "Sistema"

    def validate(self, attrs):
        audience = attrs.get("audience", getattr(self.instance, "audience", None))
        if audience == Message.Audience.PATIENT:
            raise serializers.ValidationError(
                {"audience": "Patients are notified automatically; they cannot be composed here."}
            )
        channel = attrs.get("channel", getattr(self.instance, "channel", None))
        if channel != Message.Channel.EMAIL:
            raise serializers.ValidationError(
                {"channel": "Staff messages are email-only in this version."}
            )

        request = self.context.get("request")
        user = getattr(request, "user", None) if request else None
        kind = attrs.get("kind", getattr(self.instance, "kind", None))
        priority = attrs.get("priority", getattr(self.instance, "priority", Message.Priority.NORMAL))
        if (kind == Message.Kind.ALERTA or priority == Message.Priority.ALERTA) and not (
            user and user.is_admin
        ):
            raise serializers.ValidationError(
                {"kind": "Only an administrator may send an Alerta."}
            )

        if self.instance is None:
            recipients = attrs.get("recipients") or {}
            if not (
                recipients.get("all_staff")
                or recipients.get("roles")
                or recipients.get("user_ids")
            ):
                raise serializers.ValidationError(
                    {"recipients": "At least one recipient group or person is required."}
                )
        return attrs


class DeliverySerializer(serializers.ModelSerializer):
    user_name = serializers.SerializerMethodField()
    patient_name = serializers.SerializerMethodField()
    appointment_date = serializers.SerializerMethodField()
    address_masked = serializers.SerializerMethodField()

    class Meta:
        model = Delivery
        fields = [
            "id",
            "message",
            "user",
            "user_name",
            "patient",
            "patient_name",
            "appointment",
            "appointment_date",
            "address_masked",
            "status",
            "error",
            "sent_at",
            "delivered_at",
            "read_at",
            "created_at",
        ]
        read_only_fields = fields

    def get_user_name(self, obj) -> str | None:
        return full_name_or_username(obj.user) if obj.user else None

    def get_patient_name(self, obj) -> str | None:
        return obj.patient.full_name if obj.patient else None

    def get_appointment_date(self, obj):
        return obj.appointment.date_time if obj.appointment else None

    def get_address_masked(self, obj) -> str:
        address = obj.address or ""
        if "@" in address:
            local, _, domain = address.partition("@")
            return f"{local[:1]}***@{domain}"
        digits = address[-4:] if len(address) >= 4 else address
        return f"***{digits}"
