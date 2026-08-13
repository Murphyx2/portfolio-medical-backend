import hashlib
import hmac
import logging

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings

logger = logging.getLogger(__name__)

_cipher: Fernet | None = None


def get_cipher() -> Fernet:
    global _cipher
    if _cipher is None:
        key = settings.PII_FIELD_KEY
        if not key:
            raise ValueError(
                "PII_FIELD_KEY is not configured. Generate one with "
                "`python -c \"from cryptography.fernet import Fernet; "
                "print(Fernet.generate_key().decode())\"` and set it in the env."
            )
        _cipher = Fernet(key.encode())
    return _cipher


def encrypt_plaintext(value: str) -> str:
    return get_cipher().encrypt(value.encode()).decode()


def decrypt_token(value: str) -> str:
    try:
        return get_cipher().decrypt(value.encode()).decode()
    except InvalidToken:
        # Fail closed: never surface raw ciphertext to clients.
        logger.error("Failed to decrypt a PII value; failing closed.", exc_info=True)
        raise ValueError("An encrypted field could not be decrypted.")


def is_encrypted(value: str) -> bool:
    return value.startswith("gAAAA")


def _blind_index_key() -> bytes:
    """Derived from PII_FIELD_KEY via domain separation -- no second secret to
    provision, and it rotates automatically whenever PII_FIELD_KEY does."""
    return hmac.new(
        settings.PII_FIELD_KEY.encode(), b"patient-id-blind-index-v1", hashlib.sha256
    ).digest()


def blind_index_digits(value: str) -> str:
    """Keyed hash of the complete digits-only identifier (cedula/NSS) for exact-
    match search without ever decrypting the field (see M-01 in PROGRESS.md)."""
    digits = "".join(ch for ch in (value or "") if ch.isdigit())
    if not digits:
        return ""
    return hmac.new(_blind_index_key(), digits.encode(), hashlib.sha256).hexdigest()
