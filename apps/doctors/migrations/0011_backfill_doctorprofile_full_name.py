from django.db import migrations


def backfill_full_name(apps, schema_editor):
    # Historical models only get the auto-added default manager (plain,
    # unfiltered) unless a manager sets use_in_migrations = True -- so
    # `.objects` here is unfiltered (includes soft-deleted rows), unlike
    # the real SoftDeleteManager at runtime.
    DoctorProfile = apps.get_model("doctors", "DoctorProfile")
    for doctor in DoctorProfile.objects.filter(
        full_name="", user__isnull=False
    ).select_related("user"):
        # Historical models don't carry methods like get_full_name(), only
        # fields -- build the name from first_name/last_name directly.
        full_name = f"{doctor.user.first_name} {doctor.user.last_name}".strip() or doctor.user.username
        DoctorProfile.objects.filter(pk=doctor.pk).update(full_name=full_name)


class Migration(migrations.Migration):

    dependencies = [
        ('doctors', '0010_doctorprofile_full_name_nullable_user'),
    ]

    operations = [
        migrations.RunPython(backfill_full_name, migrations.RunPython.noop),
    ]
