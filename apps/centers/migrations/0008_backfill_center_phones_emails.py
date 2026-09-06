# Data migration: backfill MedicalCenterPhone/MedicalCenterEmail from the
# legacy MedicalCenter.phone/email columns, which are kept (not dropped) for
# backward compatibility. Idempotent -- only creates a row when the center
# has none yet, so re-running (or a center created after this migration
# already has its own explicit phones/emails) never duplicates rows.

from django.db import migrations


def backfill_phones_and_emails(apps, schema_editor):
    MedicalCenter = apps.get_model("centers", "MedicalCenter")
    MedicalCenterPhone = apps.get_model("centers", "MedicalCenterPhone")
    MedicalCenterEmail = apps.get_model("centers", "MedicalCenterEmail")

    for center in MedicalCenter.objects.all():
        if center.phone and not MedicalCenterPhone.objects.filter(center=center).exists():
            MedicalCenterPhone.objects.create(center=center, number=center.phone, order=0)
        if center.email and not MedicalCenterEmail.objects.filter(center=center).exists():
            MedicalCenterEmail.objects.create(center=center, email=center.email, order=0)


class Migration(migrations.Migration):

    dependencies = [
        ("centers", "0007_medicalcenter_logo_medicalcenter_nombre_corto_and_more"),
    ]

    operations = [
        migrations.RunPython(backfill_phones_and_emails, migrations.RunPython.noop),
    ]
