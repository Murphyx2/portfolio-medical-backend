from django.core.signing import BadSignature, TimestampSigner
from django.db.models import Q

from apps.core.models import AuditLog

# How long a signed media URL stays valid (seconds).
MEDIA_TOKEN_MAX_AGE = 60 * 60


def patient_ids_matching_digits(term: str):
    """Patient ids whose cedula/NSS trailing digits match a search term.

    Non-digit characters (spaces, hyphens from the formatted display like
    ``001-1234567-8``) are stripped before matching. The match runs in SQL on
    the plaintext ``cedula_last4``/``nss_last4`` index columns (M-01) so a
    digit search never has to decrypt every row in Python: terms of 4+ digits
    compare against the stored last-4 exactly, shorter terms use a substring
    match on those columns.

    Returns a ``values_list("id")`` queryset so the caller can use it as an
    ``id__in`` subquery; the underlying query runs once, in the database.
    """
    digits = "".join(ch for ch in term if ch.isdigit())
    from apps.patients.models import Patient

    if not digits:
        return Patient.objects.none().values_list("id", flat=True)
    tail = digits[-4:]
    if len(digits) >= 4:
        q = Q(cedula_last4=tail) | Q(nss_last4=tail)
    else:
        q = Q(cedula_last4__icontains=tail) | Q(nss_last4__icontains=tail)
    return Patient.objects.filter(q).values_list("id", flat=True)


def sign_media_token(file_path: str) -> str:
    """Short-lived signed token for an authenticated media URL."""
    return TimestampSigner().sign(file_path)


def verify_media_token(file_path: str, token: str, max_age: int = MEDIA_TOKEN_MAX_AGE) -> bool:
    try:
        return TimestampSigner().unsign(token, max_age=max_age) == file_path
    except BadSignature:
        return False


def user_accessible_center_ids(user) -> set[int]:
    """Center ids a user may work with.

    Admins can access all centers. Doctors are scoped to their approved
    center bindings. Other staff roles have no center relationship in the
    data model yet, so they are treated as center-agnostic (full scope).
    """
    if not getattr(user, "is_authenticated", False):
        return set()
    if getattr(user, "is_admin", False):
        return set()
    if getattr(user, "is_doctor", False):
        from apps.centers.models import DoctorCenterBinding

        return set(
            DoctorCenterBinding.objects.filter(
                doctor__user=user, approved=True
            ).values_list("center_id", flat=True)
        )
    return set()


def log_audit(
    *,
    user,
    action: str,
    target=None,
    target_type: str = "",
    target_id: int | None = None,
    ip_address: str | None = None,
    details: dict | None = None,
) -> AuditLog:
    if target is not None:
        target_type = target_type or target.__class__.__name__
        target_id = target.pk
    return AuditLog.objects.create(
        user=user if getattr(user, "is_authenticated", False) else None,
        action=action,
        target_type=target_type,
        target_id=target_id,
        ip_address=ip_address,
        details=details or {},
    )


def is_masked_role(user) -> bool:
    """IT and CENTER_MANAGER see masked PII; all other staff see full PII."""
    if not user or not getattr(user, "is_authenticated", False):
        return False
    return not (
        getattr(user, "is_admin", False)
        or getattr(user, "is_doctor", False)
        or getattr(user, "is_nurse", False)
        or getattr(user, "is_receptionist", False)
    )


def client_ip(request) -> str | None:
    xff = request.META.get("HTTP_X_FORWARDED_FOR")
    if xff:
        return xff.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR")
