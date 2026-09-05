import requests
from django.utils import timezone

from apps.communications.services.settings import get_communications_settings

GRAPH_API_VERSION = "v20.0"
REQUEST_TIMEOUT_SECONDS = 10


def send_whatsapp_template(delivery, template, variables: list[str]) -> None:
    """Sends a queued Delivery as a Meta WhatsApp Cloud API template message
    and updates the row in place. Never raises. `variables` is the ordered
    list of already-rendered {{n}} parameter values (see
    Template.variables_json for the name order)."""
    Status = delivery.__class__.Status
    comm_settings = get_communications_settings()
    delivery.attempts += 1

    if not comm_settings.whatsapp_master_enabled:
        delivery.status = Status.FAILED
        delivery.error = "WhatsApp a pacientes está desactivado en Ajustes"
        delivery.save(update_fields=["status", "error", "attempts"])
        return
    if not comm_settings.whatsapp_configured():
        delivery.status = Status.FAILED
        delivery.error = "WhatsApp no está configurado en Ajustes"
        delivery.save(update_fields=["status", "error", "attempts"])
        return

    url = (
        f"https://graph.facebook.com/{GRAPH_API_VERSION}/"
        f"{comm_settings.whatsapp_phone_number_id}/messages"
    )
    payload = {
        "messaging_product": "whatsapp",
        "to": delivery.address,
        "type": "template",
        "template": {
            "name": template.provider_name,
            "language": {"code": template.language},
            "components": [
                {
                    "type": "body",
                    "parameters": [{"type": "text", "text": str(v)} for v in variables],
                }
            ],
        },
    }
    try:
        response = requests.post(
            url,
            json=payload,
            headers={"Authorization": f"Bearer {comm_settings.whatsapp_access_token}"},
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        if response.status_code >= 400:
            delivery.status = Status.FAILED
            delivery.error = response.text[:2000]
        else:
            data = response.json()
            delivery.status = Status.SENT
            delivery.sent_at = timezone.now()
            delivery.provider_message_id = (
                (data.get("messages") or [{}])[0].get("id", "")[:128]
            )
            delivery.error = ""
    except requests.RequestException as exc:
        delivery.status = Status.FAILED
        delivery.error = str(exc)[:2000]

    delivery.save(
        update_fields=["status", "error", "attempts", "sent_at", "provider_message_id"]
    )
