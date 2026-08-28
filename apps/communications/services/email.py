from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.utils import timezone

from apps.communications.services.settings import get_communications_settings

FOOTER = (
    "Este mensaje fue enviado desde MedicalConsultations. "
    "No responda con información clínica de pacientes."
)


def _from_header(comm_settings) -> str:
    default_from = getattr(settings, "DEFAULT_FROM_EMAIL", "") or "no-reply@localhost"
    if comm_settings.from_name:
        # "Name <address>" header form.
        address = default_from.split("<")[-1].rstrip(">") if "<" in default_from else default_from
        return f"{comm_settings.from_name} <{address}>"
    return default_from


def send_email(delivery, subject: str, body: str) -> None:
    """Sends a queued Delivery over the project's existing EMAIL_* backend
    and updates the row in place. Never raises -- failures are captured onto
    the delivery so the caller (a management command / test-send view) can
    decide what to do next without a try/except of its own."""
    comm_settings = get_communications_settings()
    full_body = f"{body}\n\n---\n{FOOTER}"
    try:
        message = EmailMultiAlternatives(
            subject=subject,
            body=full_body,
            from_email=_from_header(comm_settings),
            to=[delivery.address],
            reply_to=[comm_settings.reply_to] if comm_settings.reply_to else None,
        )
        message.attach_alternative(full_body.replace("\n", "<br>"), "text/html")
        message.send(fail_silently=False)
        delivery.status = delivery.__class__.Status.SENT
        delivery.sent_at = timezone.now()
        delivery.error = ""
    except Exception as exc:  # noqa: BLE001 -- provider/network errors are expected
        delivery.status = delivery.__class__.Status.FAILED
        delivery.error = str(exc)[:2000]
    delivery.attempts += 1
    delivery.save(update_fields=["status", "sent_at", "error", "attempts"])
