from datetime import timedelta

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from apps.appointments.models import Appointment
from apps.communications.models import Delivery, Message, Template
from apps.communications.services.appointments import active_whatsapp_template
from apps.communications.services.recipients import resolve_patient_recipient
from apps.communications.services.settings import get_communications_settings


class Command(BaseCommand):
    """Queues a CITA_RECORDATORIO WhatsApp message for every CONFIRMED
    appointment starting in ~`whatsapp_reminder_hours` (default 24h). Meant
    to run periodically (e.g. hourly) via OS cron / a scheduler container --
    no celery in this repo (see apps/appointments/services.py precedent).
    Idempotent: one reminder per (appointment, kind) ever -- an appointment
    already carrying a QUEUED/SENT/FAILED CITA_RECORDATORIO Message is
    skipped, matching spec §7.3's "one delivery per (appointment, kind,
    scheduled_slot)" rule (v1 has one reminder slot per appointment)."""

    help = "Queue WhatsApp appointment reminders due in the configured lead time."

    @transaction.atomic
    def handle(self, *args, **options):
        comm_settings = get_communications_settings()
        if not comm_settings.whatsapp_master_enabled or not comm_settings.whatsapp_configured():
            self.stdout.write("WhatsApp not configured/enabled -- nothing to do.")
            return

        template = active_whatsapp_template(Template.Kind.CITA_RECORDATORIO)
        if template is None:
            self.stdout.write(self.style.WARNING("No active CITA_RECORDATORIO template -- skipping."))
            return

        lead = timedelta(hours=comm_settings.whatsapp_reminder_hours)
        now = timezone.now()
        window_start = now + lead - timedelta(minutes=30)
        window_end = now + lead + timedelta(minutes=30)

        already_notified_ids = Message.objects.filter(
            kind=Template.Kind.CITA_RECORDATORIO,
            appointment_id__in=Appointment.objects.filter(
                status=Appointment.Status.CONFIRMED,
                date_time__gte=window_start,
                date_time__lte=window_end,
            ).values_list("id", flat=True),
        ).values_list("appointment_id", flat=True)

        due = Appointment.objects.filter(
            status=Appointment.Status.CONFIRMED,
            date_time__gte=window_start,
            date_time__lte=window_end,
        ).exclude(id__in=already_notified_ids).select_related("patient", "center", "doctor__user")

        queued = 0
        for appointment in due:
            phone = resolve_patient_recipient(
                appointment.patient, comm_settings.whatsapp_default_country_code
            )
            if not phone:
                continue
            message = Message.objects.create(
                channel=Message.Channel.WHATSAPP,
                audience=Message.Audience.PATIENT,
                kind=Template.Kind.CITA_RECORDATORIO,
                template=template,
                status=Message.Status.QUEUED,
                appointment=appointment,
                created_by=None,
            )
            Delivery.objects.create(
                message=message,
                patient=appointment.patient,
                appointment=appointment,
                address=phone,
                status=Delivery.Status.QUEUED,
            )
            queued += 1

        self.stdout.write(self.style.SUCCESS(f"Queued {queued} reminder(s)."))
