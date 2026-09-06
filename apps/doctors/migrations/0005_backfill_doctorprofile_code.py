from django.db import migrations


def backfill_codes(apps, schema_editor):
    DoctorProfile = apps.get_model("doctors", "DoctorProfile")
    for profile in DoctorProfile.objects.filter(code__isnull=True).order_by("id"):
        profile.code = f"DR{profile.id:04d}"
        profile.save(update_fields=["code"])


class Migration(migrations.Migration):

    dependencies = [
        ('doctors', '0004_doctorprofile_code'),
    ]

    operations = [
        migrations.RunPython(backfill_codes, migrations.RunPython.noop),
    ]
