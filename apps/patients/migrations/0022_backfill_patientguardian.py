"""Backfill PatientGuardian rows from Patient's old flat guardian_* fields.

One PatientGuardian row per patient that has any guardian data on file.
Reads the *old* columns before 0023 removes them from Patient -- this
migration's historical Patient model state still has them (they aren't
dropped until the following migration).
"""

from django.db import migrations

from apps.core.encryption import blind_index_digits


def backfill(apps, schema_editor):
    Patient = apps.get_model("patients", "Patient")
    PatientGuardian = apps.get_model("patients", "PatientGuardian")
    for p in Patient.objects.all().only(
        "id",
        "guardian_first_name",
        "guardian_last_name",
        "guardian_cedula",
        "guardian_nss",
        "guardian_phone",
    ):
        has_any = any(
            [
                p.guardian_first_name,
                p.guardian_last_name,
                p.guardian_cedula,
                p.guardian_nss,
                p.guardian_phone,
            ]
        )
        if not has_any:
            continue
        PatientGuardian.objects.create(
            patient_id=p.id,
            first_name=p.guardian_first_name,
            last_name=p.guardian_last_name,
            cedula=p.guardian_cedula,
            nss=p.guardian_nss,
            phone=p.guardian_phone,
            cedula_last4=(p.guardian_cedula or "")[-4:],
            cedula_hash=blind_index_digits(p.guardian_cedula or ""),
        )


class Migration(migrations.Migration):

    dependencies = [
        ("patients", "0021_patientguardian"),
    ]

    operations = [
        migrations.RunPython(backfill, migrations.RunPython.noop),
    ]
