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
    Intentionally outside the HTTP request path (spec §3/§11).

    Claims deliveries before sending them (see _claim_deliveries) so an
    overlapping/concurrent run of this same command -- a slow run bleeding
    past its scheduling interval, a manual debug invocation, or the service
    ever being scaled to more than one replica -- can never pick up the same
    QUEUED delivery twice and send a duplicate WhatsApp/email to a patient."""

    help = "Send queued Comunicaciones messages (staff email + patient WhatsApp)."

    def handle(self, *args, **options):
        sent_total = 0
        # Materialized up front, not a lazy .iterator() -- the claim/finalize
        # steps below mutate Message.status, and iterating a queryset while
        # writing to the table it's filtering on is exactly the kind of
        # stale-read hazard this command is being fixed to avoid.
        message_ids = list(
            Message.objects.filter(status=Message.Status.QUEUED).values_list("id", flat=True)
        )
        for message_id in message_ids:
            sent_total += self._send_message(message_id)
        self.stdout.write(self.style.SUCCESS(f"Processed {sent_total} deliveries."))

    @transaction.atomic
    def _claim_deliveries(self, message_id: int) -> list[Delivery]:
        """Locks and claims up to BATCH_SIZE QUEUED deliveries for one
        message, flipping them (and the parent message, if still QUEUED) to
        SENDING inside one short transaction. skip_locked=True: a concurrent
        run racing for the same rows simply gets none of them this pass
        rather than blocking -- the network sends happen outside this
        transaction, in _send_message, so a slow WhatsApp/email API call
        never holds a DB lock. select_for_update is a silent no-op on the
        SQLite test backend (Django only emits FOR UPDATE when the
        connection reports support for it), so this is safe to exercise in
        tests but only actually serializes concurrent runs on Postgres."""
        deliveries = list(
            Delivery.objects.select_for_update(skip_locked=True)
            .filter(message_id=message_id, status=Delivery.Status.QUEUED)[:BATCH_SIZE]
        )
        if not deliveries:
            return []
        Delivery.objects.filter(pk__in=[d.pk for d in deliveries]).update(
            status=Delivery.Status.SENDING
        )
        # Conditional UPDATE (not a read-then-write) -- a concurrent claim on
        # this same message_id that already flipped it out of QUEUED is a
        # no-op here, never an overwrite.
        Message.objects.filter(pk=message_id, status=Message.Status.QUEUED).update(
            status=Message.Status.SENDING
        )
        for delivery in deliveries:
            delivery.status = Delivery.Status.SENDING
        return deliveries

    def _send_message(self, message_id: int) -> int:
        deliveries = self._claim_deliveries(message_id)
        if not deliveries:
            return 0

        message = Message.objects.get(pk=message_id)
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
                variables = (
                    render_appointment_variables(delivery.appointment, template)
                    if delivery.appointment
                    else []
                )
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
