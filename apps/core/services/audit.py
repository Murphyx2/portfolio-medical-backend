from apps.core.models import AuditLog


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
