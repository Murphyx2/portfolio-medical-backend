"""Backfill the cedula_hash/nss_hash blind index for existing patients.

Same pattern as 0007_backfill_patient_last4: read each patient's
(transparently decrypted) cedula/NSS once and derive the keyed hash, so full-
number search never has to decrypt on every query.
"""

from django.db import migrations

from apps.core.encryption import blind_index_digits


def backfill(apps, schema_editor):
    Patient = apps.get_model("patients", "Patient")
    for p in Patient.objects.all().only("id", "cedula", "nss"):
        p.cedula_hash = blind_index_digits(p.cedula)
        p.nss_hash = blind_index_digits(p.nss)
        p.save(update_fields=["cedula_hash", "nss_hash"])


class Migration(migrations.Migration):

    dependencies = [
        ("patients", "0010_patient_cedula_hash_patient_nss_hash"),
    ]

    operations = [
        migrations.RunPython(backfill, migrations.RunPython.noop),
    ]
