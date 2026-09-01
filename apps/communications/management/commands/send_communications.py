from django.core.management.base import BaseCommand
from django.db import transaction

from apps.communications.models import Delivery, Message
from apps.communications.services.appointments import render_appointment_variables
from apps.communications.services.email import send_email
from apps.communications.services.whatsapp import send_whatsapp_template

BATCH_SIZE = 50


class Command(BaseCommand):
    """Sends every QUEUED Message's QUEUED deliveries. No celery/cron in
    this repo (see apps/appointments/services.py precedent) -- run this
    periodically (e.g. every minute) via OS cron / a scheduler container.
    Intentionally outside the HTTP request path (spec §3/§11)."""

    help = "Send queued Comunicaciones messages (staff email + patient WhatsApp)."

    def handle(self, *args, **options):
        sent_total = 0
        for message in Message.objects.filter(status=Message.Status.QUEUED).iterator():
            sent_total += self._send_message(message)
        self.stdout.write(self.style.SUCCESS(f"Processed {sent_total} deliveries."))

    def _send_message(self, message: Message) -> int:
        deliveries = list(
            message.deliveries.filter(status=Delivery.Status.QUEUED)[:BATCH_SIZE]
        )
        if not deliveries:
            return 0

        message.status = Message.Status.SENDING
        message.save(update_fields=["status"])

        sent_count = 0
        for delivery in deliveries:
            if message.channel == Message.Channel.EMAIL:
                send_email(delivery, message.subject, message.body)
            else:
                template = message.template
                if template is None:
                    delivery.status = Delivery.Status.FAILED
                    delivery.error = f"Falta plantilla de WhatsApp para {message.kind}"
                    delivery.save(update_fields=["status", "error"])
                    continue
                variables = render_appointment_variables(delivery.appointment, template) if delivery.appointment else []
                send_whatsapp_template(delivery, template, variables)
            if delivery.status == Delivery.Status.SENT:
                sent_count += 1

        self._finalize_status(message)
        return sent_count

    @transaction.atomic
    def _finalize_status(self, message: Message) -> None:
        remaining_queued = message.deliveries.filter(status=Delivery.Status.QUEUED).exists()
        if remaining_queued:
            message.status = Message.Status.QUEUED
        else:
            statuses = set(message.deliveries.values_list("status", flat=True))
            failed_like = {Delivery.Status.FAILED, Delivery.Status.UNDELIVERABLE}
            if statuses and statuses.issubset(failed_like):
                message.status = Message.Status.FAILED
            elif statuses & failed_like:
                message.status = Message.Status.PARTIAL
            else:
                message.status = Message.Status.SENT
        message.save(update_fields=["status"])
