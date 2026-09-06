import re
import unicodedata

from django.core.exceptions import ValidationError as DjangoValidationError
from django.utils.translation import gettext as _
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


class SettingsMinimumLengthValidator:
    """Drop-in replacement for Django's own MinimumLengthValidator in
    AUTH_PASSWORD_VALIDATORS, except the minimum reads from the runtime-
    configurable SystemSettings singleton (apps.systemsettings.services.
    get_settings) instead of a fixed constructor argument."""

    def validate(self, password, user=None):
        from apps.systemsettings.services import get_settings

        min_length = get_settings().password_min_length
        if len(password) < min_length:
            raise DjangoValidationError(
                _(
                    "This password is too short. It must contain at least "
                    "%(min_length)d characters."
                ),
                code="password_too_short",
                params={"min_length": min_length},
            )

    def get_help_text(self):
        from apps.systemsettings.services import get_settings

        min_length = get_settings().password_min_length
        return _(
            "Your password must contain at least %(min_length)d characters."
        ) % {"min_length": min_length}
