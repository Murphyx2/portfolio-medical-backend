def is_masked_role(user) -> bool:
    """IT sees masked PII; all other staff (including CENTER_MANAGER, which
    is admin-equivalent app-wide except Settings) see full PII."""
    if not user or not getattr(user, "is_authenticated", False):
        return False
    return not (
        getattr(user, "is_admin", False)
        or getattr(user, "is_doctor", False)
        or getattr(user, "is_nurse", False)
        or getattr(user, "is_receptionist", False)
        or getattr(user, "is_center_manager", False)
    )
