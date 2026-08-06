from django.core.signing import BadSignature, TimestampSigner

from apps.core.models import AuditLog

# How long a signed media URL stays valid (seconds).
MEDIA_TOKEN_MAX_AGE = 60 * 60


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


def client_ip(request) -> str | None:
    xff = request.META.get("HTTP_X_FORWARDED_FOR")
    if xff:
        return xff.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR")
