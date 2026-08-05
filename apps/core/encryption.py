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
