from django.db import models

from .encryption import decrypt_token, is_encrypted


class EncryptedTextField(models.TextField):
    """Stores Fernet-encrypted text at rest; transparently decrypts on read."""

    description = "Fernet-encrypted text"

    def get_db_prep_save(self, value, connection):
        if value is None or value == "":
            return value
        return value if is_encrypted(str(value)) else self._encrypt(str(value))

    def from_db_value(self, value, expression, connection, context=None):
        if value is None or value == "":
            return value
        return decrypt_token(str(value))

    def to_python(self, value):
        if value is None:
            return value
        return value if not is_encrypted(str(value)) else decrypt_token(str(value))

    @staticmethod
    def _encrypt(value: str) -> str:
        from .encryption import encrypt_plaintext

        return encrypt_plaintext(value)


class EncryptedCharField(EncryptedTextField):
    """CharField version of EncryptedTextField."""

    description = "Fernet-encrypted string"

    def __init__(self, *args, max_length=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.max_length = max_length
