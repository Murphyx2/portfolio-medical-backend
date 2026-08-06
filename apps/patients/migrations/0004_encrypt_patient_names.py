# Data migration: encrypt pre-existing plaintext name/birth-date columns and
# populate search_name. Runs in its own transaction, after the schema changes
# (0003) commit, so Postgres does not report "pending trigger events" when the
# search_name index is created afterwards (0005).
from django.db import connection, migrations

from apps.core.encryption import encrypt_plaintext, is_encrypted


def encrypt_patient_names(apps, schema_editor):
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT id, first_name, last_name, birth_date FROM patients_patient"
        )
        for pk, first, last, birth in cursor.fetchall():
            updates = {}
            search_name = ""
            if first and not is_encrypted(first):
                updates["first_name"] = encrypt_plaintext(first)
                search_name += first
            elif first:
                search_name += first
            if last and not is_encrypted(last):
                updates["last_name"] = encrypt_plaintext(last)
                search_name += (" " + last) if search_name else last
            elif last:
                search_name += (" " + last) if search_name else last
            if birth and not is_encrypted(str(birth)):
                updates["birth_date"] = encrypt_plaintext(str(birth))
            if search_name:
                updates["search_name"] = search_name.strip().lower()
            if updates:
                set_clause = ", ".join(f"{k} = %s" for k in updates)
                cursor.execute(
                    f"UPDATE patients_patient SET {set_clause} WHERE id = %s",
                    [*updates.values(), pk],
                )


class Migration(migrations.Migration):

    dependencies = [
        ('patients', '0003_alter_patient_options_and_more'),
    ]

    operations = [
        migrations.RunPython(encrypt_patient_names, migrations.RunPython.noop),
    ]
