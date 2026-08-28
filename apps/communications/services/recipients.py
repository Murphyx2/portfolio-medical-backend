from apps.accounts.models import User
from apps.communications.models import OptOut
from apps.communications.services.phone import to_e164


def resolve_staff_recipients(
    all_staff: bool, roles: list[str], user_ids: list[int]
) -> tuple[list[User], list[User]]:
    """Resolve a staff-email RecipientSpec into
    (recipients_with_email, recipients_without_email), deduplicated (a user
    matching several groups is counted once)."""
    qs = User.objects.none()
    if all_staff:
        qs = User.objects.filter(is_active=True)
    else:
        filters = None
        if roles:
            filters = User.objects.filter(is_active=True, role__in=roles)
        if user_ids:
            by_id = User.objects.filter(is_active=True, pk__in=user_ids)
            filters = by_id if filters is None else (filters | by_id)
        qs = filters if filters is not None else User.objects.none()

    users = list(qs.distinct())
    with_email = [u for u in users if u.email]
    without_email = [u for u in users if not u.email]
    return with_email, without_email


def resolve_patient_recipient(patient, country_code: str = "+1") -> str | None:
    """E.164 phone to notify a patient on WhatsApp, or None if any consent
    precondition fails (no phone, opted out, opted-out-by-keyword, or the
    patient record itself is inactive)."""
    if not patient or not patient.active or not patient.whatsapp_opt_in or not patient.phone:
        return None
    phone = to_e164(patient.phone, country_code)
    if not phone:
        return None
    if OptOut.objects.filter(patient=patient, phone_e164=phone).exists():
        return None
    return phone
