"""Backfill Encounter.service_type for existing rows.

This app is still pre-release/unmerged with only dev/test data, so there's
no meaningful mapping from the old encounter_type to a specific ServiceType
-- every row just gets whatever ServiceType happens to exist first.
"""

from django.db import migrations


def populate(apps, schema_editor):
    Encounter = apps.get_model("encounters", "Encounter")
    ServiceType = apps.get_model("services", "ServiceType")
    fallback = ServiceType.objects.first()
    if fallback is None:
        return
    Encounter.objects.filter(service_type__isnull=True).update(service_type=fallback)


class Migration(migrations.Migration):

    dependencies = [
        ('encounters', '0003_encounter_service_type_temp'),
    ]

    operations = [
        migrations.RunPython(populate, migrations.RunPython.noop),
    ]
