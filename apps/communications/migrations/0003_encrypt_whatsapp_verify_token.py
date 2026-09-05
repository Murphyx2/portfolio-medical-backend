# Data migration: encrypt a pre-existing plaintext whatsapp_verify_token
# value, if one was set before 0002 switched the field to EncryptedCharField.
# Uses raw SQL (not the ORM) so this never triggers EncryptedCharField's
# decrypt-on-read against a not-yet-encrypted value -- see
# apps/patients/migrations/0004_encrypt_patient_names.py for the same pattern.
from django.db import connection, migrations

from apps.core.encryption import encrypt_plaintext, is_encrypted


def encrypt_verify_token(apps, schema_editor):
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT id, whatsapp_verify_token FROM communications_communicationssettings"
        )
        rows = cursor.fetchall()
        for pk, token in rows:
            if token and not is_encrypted(token):
                cursor.execute(
                    "UPDATE communications_communicationssettings "
                    "SET whatsapp_verify_token = %s WHERE id = %s",
                    [encrypt_plaintext(token), pk],
                )


class Migration(migrations.Migration):

    dependencies = [
        ('communications', '0002_alter_communicationssettings_whatsapp_verify_token'),
    ]

    operations = [
        migrations.RunPython(encrypt_verify_token, migrations.RunPython.noop),
    ]
