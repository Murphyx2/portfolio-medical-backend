import re


def to_e164(raw: str, country_code: str = "+1") -> str | None:
    """Normalize a Patient.phone value (stored as a bare 10-digit DR local
    number, see apps.core.validators.DR_PHONE_LENGTH) to E.164. Defensive
    against already-prefixed or malformed input -- never raises, callers
    mark the delivery UNDELIVERABLE on a None return instead of crashing a
    send job."""
    if not raw:
        return None
    raw = raw.strip()
    if raw.startswith("+"):
        digits = re.sub(r"\D", "", raw)
        return f"+{digits}" if digits else None
    digits = re.sub(r"\D", "", raw)
    if len(digits) == 10:
        return f"{country_code}{digits}"
    if len(digits) > 10:
        # Already carries a country code without the leading '+'.
        return f"+{digits}"
    return None
