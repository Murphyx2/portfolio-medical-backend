from django.db import migrations


def split_full_name(apps, schema_editor):
    DoctorProfile = apps.get_model("doctors", "DoctorProfile")
    for doctor in DoctorProfile.objects.exclude(full_name=""):
        parts = doctor.full_name.rsplit(" ", 1)
        first_name = parts[0]
        last_name = parts[1] if len(parts) > 1 else ""
        DoctorProfile.objects.filter(pk=doctor.pk).update(
            first_name=first_name, last_name=last_name
        )


class Migration(migrations.Migration):

    dependencies = [
        ('doctors', '0012_doctorprofile_split_first_last_name'),
    ]

    operations = [
        migrations.RunPython(split_full_name, migrations.RunPython.noop),
    ]
