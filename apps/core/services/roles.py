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
