"""Backfill the plaintext cedula_last4/nss_last4 index for existing patients.

The values are derived from the (encrypted-at-rest) cedula/NSS, decrypting each
row once so digit search can run in SQL instead of decrypting on every query.
"""

from django.db import migrations


def backfill(apps, schema_editor):
    Patient = apps.get_model("patients", "Patient")
    for p in Patient.objects.all().only("id", "cedula", "nss"):
        p.cedula_last4 = (p.cedula or "")[-4:]
        p.nss_last4 = (p.nss or "")[-4:]
        p.save(update_fields=["cedula_last4", "nss_last4"])


class Migration(migrations.Migration):

    dependencies = [
        ("patients", "0006_patient_cedula_last4_patient_nss_last4"),
    ]

    operations = [
        migrations.RunPython(backfill, migrations.RunPython.noop),
    ]
