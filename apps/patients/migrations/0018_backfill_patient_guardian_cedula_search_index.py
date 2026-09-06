"""Backfill guardian_cedula_last4/guardian_cedula_hash for existing patients.

Same pattern as 0007_backfill_patient_last4 / 0011_backfill_patient_hash: read
each patient's (transparently decrypted) guardian_cedula once and derive the
plaintext last4 + keyed hash, so a guardian-cedula search never has to
decrypt on every query.
"""

from django.db import migrations

from apps.core.encryption import blind_index_digits


def backfill(apps, schema_editor):
    Patient = apps.get_model("patients", "Patient")
    for p in Patient.objects.all().only("id", "guardian_cedula"):
        p.guardian_cedula_last4 = (p.guardian_cedula or "")[-4:]
        p.guardian_cedula_hash = blind_index_digits(p.guardian_cedula)
        p.save(update_fields=["guardian_cedula_last4", "guardian_cedula_hash"])


class Migration(migrations.Migration):

    dependencies = [
        ("patients", "0017_patient_guardian_cedula_search_index"),
    ]

    operations = [
        migrations.RunPython(backfill, migrations.RunPython.noop),
    ]
