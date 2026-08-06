import re
import unicodedata

from rest_framework import serializers

DR_PHONE_LENGTH = 10

# Allowed phone separators after NFKC normalization (spaces, parens, dash,
# dot, leading plus). Anything else (letters, symbols, non-ASCII digits that
# do not fold to ASCII) is rejected.
_ALLOWED = re.compile(r"[^\d\s()+\-.]")


def validate_phone(value: str) -> str:
    """Require exactly 10 digits, reject letters, and normalize to ASCII digits."""
    if not value:
        return value
    # NFKC folds fullwidth/halfwidth forms into ASCII (e.g. "８０９" -> "809")
    # so the checks below operate on a predictable character set.
    normalized = unicodedata.normalize("NFKC", str(value))
    # Reject non-ASCII leftovers (accented letters, Arabic-Indic digits, ...).
    if not normalized.isascii():
        raise serializers.ValidationError("Phone cannot contain letters.")
    if _ALLOWED.search(normalized):
        raise serializers.ValidationError("Phone cannot contain letters.")
    digits = re.sub(r"\D", "", normalized)
    if len(digits) != DR_PHONE_LENGTH:
        raise serializers.ValidationError("Phone must contain exactly 10 digits.")
    return digits
