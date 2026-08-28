import hashlib
import hmac
import json
import logging

from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.generics import RetrieveUpdateAPIView
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from apps.communications.models import CommunicationsSettings, Delivery, Message, OptOut, Template
from apps.communications.serializers import (
    CommunicationsSettingsSerializer,
    DeliverySerializer,
    MessageSerializer,
    TemplateSerializer,
)
from apps.communications.services.appointments import active_whatsapp_template
from apps.communications.services.email import send_email
from apps.communications.services.phone import to_e164
from apps.communications.services.recipients import resolve_staff_recipients
from apps.communications.services.settings import get_communications_settings
from apps.core.mixins import AuditMixin, SwapPermissionsMixin
from apps.core.permissions import CanSendStaffEmail, IsAdmin, IsStaffUser
from apps.core.services import client_ip, log_audit
from apps.patients.models import Patient

logger = logging.getLogger(__name__)


def _get_settings_singleton() -> CommunicationsSettings:
    obj, _created = CommunicationsSettings.objects.get_or_create(pk=1)
    return obj


class CommunicationsSettingsView(RetrieveUpdateAPIView):
    """``GET/PATCH /api/communications/settings/`` -- Admin-only (unlike
    apps.systemsettings, IT gets no read access here: WhatsApp/email
    credentials are treated as secrets, not general operational params)."""

    permission_classes = [IsAdmin]
    serializer_class = CommunicationsSettingsSerializer
    http_method_names = ["get", "patch", "head", "options"]

    def get_object(self):
        return _get_settings_singleton()

    def perform_update(self, serializer):
        instance = serializer.instance
        before = {
            field: getattr(instance, field)
            for field in serializer.validated_data
            if hasattr(instance, field)
        }
        serializer.save(updated_by=self.request.user)
        changed_fields = sorted(
            field
            for field, old_value in before.items()
            if old_value != getattr(serializer.instance, field)
        )
        log_audit(
            user=self.request.user,
            action="UPDATE",
            target=serializer.instance,
            ip_address=client_ip(self.request),
            details={"changed_fields": changed_fields} if changed_fields else None,
        )


@api_view(["POST"])
@permission_classes([IsAdmin])
def test_email(request):
    if not request.user.email:
        return Response({"detail": "Your account has no email on file."}, status=400)

    class _Delivery:
        address = request.user.email
        status = Delivery.Status.QUEUED
        error = ""
        sent_at = None
        attempts = 0

        def save(self, update_fields=None):
            pass

    delivery = _Delivery()
    send_email(delivery, "Prueba de Comunicaciones", "Este es un correo de prueba de Comunicaciones.")
    if delivery.status == Delivery.Status.SENT:
        return Response({"detail": "Correo de prueba enviado."})
    return Response({"detail": delivery.error or "No se pudo enviar."}, status=400)


@api_view(["POST"])
@permission_classes([IsAdmin])
def test_whatsapp(request):
    comm_settings = get_communications_settings()
    phone_raw = (request.data.get("phone") or "").strip()
    kind = request.data.get("kind") or Template.Kind.CITA_RECORDATORIO
    phone = to_e164(phone_raw, comm_settings.whatsapp_default_country_code)
    if not phone:
        return Response({"detail": "Numero de telefono invalido."}, status=400)

    template = active_whatsapp_template(kind)
    if template is None:
        return Response({"detail": f"Falta plantilla de WhatsApp para {kind}"}, status=400)
    if not comm_settings.whatsapp_master_enabled:
        return Response({"detail": "WhatsApp a pacientes está desactivado en Ajustes"}, status=400)
    if not comm_settings.whatsapp_configured():
        return Response({"detail": "WhatsApp no está configurado en Ajustes"}, status=400)

    from apps.communications.services.whatsapp import send_whatsapp_template

    class _Delivery:
        address = phone
        status = Delivery.Status.QUEUED
        error = ""
        sent_at = None
        provider_message_id = ""
        attempts = 0

        def save(self, update_fields=None):
            pass

    delivery = _Delivery()
    placeholder_values = [str(n) for n in range(1, len(template.variables_json or []) + 1)] or ["Prueba"]
    send_whatsapp_template(delivery, template, placeholder_values)
    if delivery.status == Delivery.Status.SENT:
        return Response({"detail": "WhatsApp de prueba enviado."})
    return Response({"detail": delivery.error or "No se pudo enviar."}, status=400)


class TemplateViewSet(AuditMixin, viewsets.ModelViewSet):
    queryset = Template.objects.all()
    serializer_class = TemplateSerializer
    permission_classes = [IsAdmin]


class MessageViewSet(SwapPermissionsMixin, AuditMixin, viewsets.ModelViewSet):
    queryset = Message.objects.filter(audience=Message.Audience.STAFF).select_related(
        "created_by", "template", "appointment"
    )
    serializer_class = MessageSerializer
    permission_classes = [IsStaffUser]
    write_permission_classes = [CanSendStaffEmail]
    http_method_names = ["get", "post", "head", "options"]

    def get_queryset(self):
        qs = super().get_queryset()
        user = self.request.user
        if user.is_admin or user.is_center_manager:
            return qs
        return qs.filter(created_by=user)

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        validated = dict(serializer.validated_data)
        recipients_spec = validated.pop("recipients", None) or {}

        with_email, without_email = resolve_staff_recipients(
            all_staff=recipients_spec.get("all_staff", False),
            roles=recipients_spec.get("roles", []),
            user_ids=recipients_spec.get("user_ids", []),
        )

        message = Message.objects.create(
            created_by=request.user,
            recipient_count=len(with_email),
            **validated,
        )
        if message.status == Message.Status.QUEUED:
            Delivery.objects.bulk_create(
                Delivery(message=message, user=u, address=u.email, status=Delivery.Status.QUEUED)
                for u in with_email
            )

        self.log_action(message, "CREATE", details={"recipient_count": len(with_email)})

        data = self.get_serializer(message).data
        data["skipped_no_email"] = len(without_email)
        headers = self.get_success_headers(data)
        return Response(data, status=status.HTTP_201_CREATED, headers=headers)

    @action(detail=False, methods=["post"], permission_classes=[CanSendStaffEmail])
    def test(self, request):
        """'Enviarme una prueba' -- sends only to the author, synchronously,
        the one deliberate exception to 'not sent inside the request'."""
        if not request.user.email:
            return Response({"detail": "Your account has no email on file."}, status=400)
        subject = request.data.get("subject") or "(sin asunto)"
        body = request.data.get("body") or ""

        class _Delivery:
            address = request.user.email
            status = Delivery.Status.QUEUED
            error = ""
            sent_at = None
            attempts = 0

            def save(self, update_fields=None):
                pass

        delivery = _Delivery()
        send_email(delivery, subject, body)
        if delivery.status == Delivery.Status.SENT:
            return Response({"detail": "Prueba enviada."})
        return Response({"detail": delivery.error or "No se pudo enviar."}, status=400)


class DeliveryViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Delivery.objects.select_related("message", "user", "patient", "appointment")
    serializer_class = DeliverySerializer
    permission_classes = [IsStaffUser]
    filterset_fields = {
        "message": ["exact"],
        "message__audience": ["exact"],
        "message__kind": ["exact"],
        "status": ["exact"],
        "created_at": ["exact", "gte", "lt"],
    }

    def get_queryset(self):
        qs = super().get_queryset()
        user = self.request.user
        if user.is_admin or user.is_center_manager:
            return qs
        return qs.filter(message__created_by=user)


@api_view(["GET", "POST"])
@permission_classes([AllowAny])
def whatsapp_webhook(request):
    comm_settings = get_communications_settings()

    if request.method == "GET":
        mode = request.GET.get("hub.mode")
        token = request.GET.get("hub.verify_token")
        challenge = request.GET.get("hub.challenge", "")
        if mode == "subscribe" and token and comm_settings.whatsapp_verify_token and hmac.compare_digest(
            token, comm_settings.whatsapp_verify_token
        ):
            return Response(int(challenge) if challenge.isdigit() else challenge)
        return Response(status=403)

    app_secret = comm_settings.whatsapp_app_secret
    signature = request.headers.get("X-Hub-Signature-256", "")
    if not app_secret or not signature.startswith("sha256="):
        return Response(status=403)
    expected = hmac.new(app_secret.encode(), request.body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature[len("sha256="):], expected):
        return Response(status=403)

    try:
        _process_webhook_payload(json.loads(request.body or b"{}"), comm_settings)
    except Exception:  # noqa: BLE001 -- Meta retries on non-2xx; never fail the webhook
        logger.exception("communications: failed to process WhatsApp webhook payload")

    return Response(status=200)


def _process_webhook_payload(payload: dict, comm_settings: CommunicationsSettings) -> None:
    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value", {})
            for status_update in value.get("statuses", []):
                _apply_status_update(status_update)
            for inbound in value.get("messages", []):
                _apply_inbound_message(inbound, comm_settings)


def _apply_status_update(status_update: dict) -> None:
    provider_id = status_update.get("id")
    new_status = (status_update.get("status") or "").lower()
    if not provider_id or new_status not in ("sent", "delivered", "read", "failed"):
        return
    delivery = Delivery.objects.filter(provider_message_id=provider_id).first()
    if delivery is None:
        return
    now = timezone.now()
    if new_status == "delivered":
        delivery.status = Delivery.Status.DELIVERED
        delivery.delivered_at = now
    elif new_status == "read":
        delivery.status = Delivery.Status.READ
        delivery.read_at = now
    elif new_status == "failed":
        delivery.status = Delivery.Status.FAILED
        errors = status_update.get("errors") or []
        delivery.error = json.dumps(errors)[:2000]
    delivery.save()


OPT_OUT_KEYWORDS = {"STOP", "SALIR", "NO", "CANCELAR"}


def _apply_inbound_message(inbound: dict, comm_settings: CommunicationsSettings) -> None:
    text = ((inbound.get("text") or {}).get("body") or "").strip().upper()
    from_number = inbound.get("from") or ""
    if text not in OPT_OUT_KEYWORDS or not from_number:
        return
    local_10 = from_number[-10:]
    # Patient.phone is a Fernet-encrypted column (non-deterministic
    # ciphertext) -- an exact DB-level filter isn't possible without a blind
    # index, so this scans only opt-in patients (small, bounded set) and
    # compares the transparently-decrypted value in Python.
    patient = next(
        (p for p in Patient.objects.filter(whatsapp_opt_in=True) if p.phone == local_10),
        None,
    )
    if patient is None:
        return
    patient.whatsapp_opt_in = False
    patient.save(update_fields=["whatsapp_opt_in"])
    e164 = to_e164(local_10, comm_settings.whatsapp_default_country_code)
    OptOut.objects.create(patient=patient, phone_e164=e164 or from_number, reason=text)
    log_audit(
        user=None,
        action="UPDATE",
        target=patient,
        details={"communication": "whatsapp_opt_out"},
    )
