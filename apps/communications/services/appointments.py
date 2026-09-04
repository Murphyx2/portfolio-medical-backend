import logging
from datetime import timedelta

from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.communications.models import Delivery, Message, Template
from apps.communications.services.recipients import resolve_patient_recipient
from apps.communications.services.settings import get_communications_settings

logger = logging.getLogger(__name__)

RATE_LIMIT_WINDOW = timedelta(hours=1)

# Re-exported so callers outside this app (apps/appointments/views.py) can
# reference the CITA_* event kinds without importing Template directly --
# the modular-monolith convention (CLAUDE.md) is cross-app calls go through
# this services module, not a raw model import.
AppointmentNotificationKind = Template.Kind


def active_whatsapp_template(kind: str) -> Template | None:
    return Template.objects.filter(
        channel=Template.Channel.WHATSAPP, kind=kind, is_active=True
    ).first()


def render_appointment_variables(appointment, template: Template) -> list[str]:
    """Ordered {{n}} parameter values for an appointment WhatsApp template,
    keyed by template.variables_json (e.g. ["nombre","clinica","fecha",
    "hora","telefono"]). Content is deliberately limited to what spec §7.4
    allows -- given name, clinic, date/time, location, doctor last name,
    callback number. Never diagnosis/motivo/expediente/NSS/Cedula."""
    patient = appointment.patient
    center = appointment.center
    local_dt = timezone.localtime(appointment.date_time)
    values_by_name = {
        "nombre": patient.first_name,
        "clinica": center.name if center else "MedicalConsultations",
        "fecha": local_dt.strftime("%d/%m/%Y"),
        "hora": local_dt.strftime("%H:%M"),
        "telefono": center.phone if center and getattr(center, "phone", "") else "",
        "doctor": appointment.doctor.user.last_name if appointment.doctor_id else "",
    }
    names = template.variables_json or ["nombre", "clinica", "fecha", "hora", "telefono"]
    return [str(values_by_name.get(name, "")) for name in names]


def notify_appointment_event(appointment, kind: str, *, user=None) -> None:
    """Best-effort queue of a patient WhatsApp notification for an
    appointment lifecycle event. Silently no-ops (no Message/Delivery row)
    when any precondition isn't met -- unconfigured WhatsApp is the normal
    state for a clinic that hasn't set it up yet, not an error worth
    recording per-appointment. Never raises out of the calling view action.
    """
    try:
        comm_settings = get_communications_settings()
        if not comm_settings.whatsapp_master_enabled or not comm_settings.whatsapp_configured():
            return
        phone = resolve_patient_recipient(
            appointment.patient, comm_settings.whatsapp_default_country_code
        )
        if not phone:
            return
        template = active_whatsapp_template(kind)
        if template is None:
            return
        message = Message.objects.create(
            channel=Message.Channel.WHATSAPP,
            audience=Message.Audience.PATIENT,
            kind=kind,
            template=template,
            status=Message.Status.QUEUED,
            appointment=appointment,
            created_by=user,
        )
        Delivery.objects.create(
            message=message,
            patient=appointment.patient,
            appointment=appointment,
            address=phone,
            status=Delivery.Status.QUEUED,
        )
    except Exception:  # noqa: BLE001 -- never break an appointment state transition
        logger.exception(
            "communications: failed to queue appointment notification (appointment=%s kind=%s)",
            appointment.pk,
            kind,
        )


def cancel_queued_reminders(appointment) -> None:
    messages = Message.objects.filter(
        appointment=appointment,
        kind=Template.Kind.CITA_RECORDATORIO,
        status=Message.Status.QUEUED,
    )
    message_ids = list(messages.values_list("id", flat=True))
    if not message_ids:
        return
    messages.update(status=Message.Status.CANCELLED)
    Delivery.objects.filter(
        message_id__in=message_ids, status=Delivery.Status.QUEUED
    ).update(status=Delivery.Status.CANCELLED)


def queue_manual_reminder(appointment, user) -> Message:
    """User-initiated 'Enviar recordatorio WhatsApp'. Unlike
    notify_appointment_event, this one surfaces a real error to the caller
    (rest_framework.exceptions.ValidationError) with the exact Spanish copy
    from spec §12, since it's a synchronous action a human is waiting on."""
    comm_settings = get_communications_settings()
    if not comm_settings.whatsapp_master_enabled:
        raise ValidationError({"detail": "WhatsApp a pacientes está desactivado en Ajustes"})
    if not comm_settings.whatsapp_configured():
        raise ValidationError({"detail": "WhatsApp no está configurado en Ajustes"})

    phone = resolve_patient_recipient(
        appointment.patient, comm_settings.whatsapp_default_country_code
    )
    if not phone:
        raise ValidationError({"detail": "El paciente no tiene WhatsApp habilitado"})

    template = active_whatsapp_template(Template.Kind.CITA_RECORDATORIO)
    if template is None:
        raise ValidationError(
            {"detail": f"Falta plantilla de WhatsApp para {Template.Kind.CITA_RECORDATORIO}"}
        )

    window_start = timezone.now() - RATE_LIMIT_WINDOW
    recently_sent = Delivery.objects.filter(
        appointment=appointment,
        message__kind=Template.Kind.CITA_RECORDATORIO,
        status=Delivery.Status.SENT,
        sent_at__gte=window_start,
    ).exists()
    if recently_sent:
        raise ValidationError(
            {"detail": "Ya se envió un recordatorio para esta cita en la última hora."}
        )

    message = Message.objects.create(
        channel=Message.Channel.WHATSAPP,
        audience=Message.Audience.PATIENT,
        kind=Template.Kind.CITA_RECORDATORIO,
        template=template,
        status=Message.Status.QUEUED,
        appointment=appointment,
        created_by=user,
    )
    Delivery.objects.create(
        message=message,
        patient=appointment.patient,
        appointment=appointment,
        address=phone,
        status=Delivery.Status.QUEUED,
    )
    return message
