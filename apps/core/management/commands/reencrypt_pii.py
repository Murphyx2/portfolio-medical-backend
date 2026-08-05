"""Re-encrypt all field-level encrypted PII from one Fernet key to another.

Usage:
    python manage.py reencrypt_pii --old-key <OLD_FERNET_KEY>

The NEW key is the currently configured ``PII_FIELD_KEY`` (settings). Run this
after rotating the key in the environment: every value stored under the old key
is read, decrypted, and re-encrypted with the configured key.

Useful when a key was ever exposed (e.g. committed to version control).
"""

from django.core.management.base import BaseCommand
from django.db import connection

from apps.core.encryption import get_cipher
from apps.core.fields import EncryptedCharField, EncryptedTextField
from apps.patients.models import Patient
from apps.records.models import ConsultationLog, MedicalRecord
from cryptography.fernet import Fernet, InvalidToken


def _encrypted_field_names(model):
    return [
        f.name
        for f in model._meta.fields
        if isinstance(f, (EncryptedCharField, EncryptedTextField))
    ]


class Command(BaseCommand):
    help = "Re-encrypt PII stored under an old Fernet key using the configured key."

    def add_arguments(self, parser):
        parser.add_argument("--old-key", required=True, help="Old Fernet key.")

    def handle(self, *args, **options):
        old_cipher = Fernet(options["old_key"].encode())
        new_cipher = get_cipher()

        total = 0
        with connection.cursor() as cursor:
            for model in (Patient, MedicalRecord, ConsultationLog):
                fields = _encrypted_field_names(model)
                table = model._meta.db_table
                cols = ", ".join(["id", *fields])
                cursor.execute(f"SELECT {cols} FROM {table}")
                for row in cursor.fetchall():
                    pk = row[0]
                    updates = {}
                    for idx, name in enumerate(fields, start=1):
                        raw = row[idx]
                        if raw is None or raw == "":
                            continue
                        try:
                            plain = old_cipher.decrypt(raw.encode()).decode()
                        except InvalidToken:
                            self.stderr.write(
                                f"WARN: {model.__name__} pk={pk} field={name}: "
                                "not decryptable with old key; skipping."
                            )
                            continue
                        updates[name] = new_cipher.encrypt(plain.encode()).decode()
                    if updates:
                        set_clause = ", ".join(f"{n} = %s" for n in updates)
                        cursor.execute(
                            f"UPDATE {table} SET {set_clause} WHERE id = %s",
                            [*updates.values(), pk],
                        )
                        total += 1
        self.stdout.write(self.style.SUCCESS(f"Re-encrypted {total} records."))
