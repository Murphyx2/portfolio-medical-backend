from django.db import migrations


def seed_defaults(apps, schema_editor):
    SystemSettings = apps.get_model("systemsettings", "SystemSettings")
    SystemSettings.objects.get_or_create(pk=1)


def unseed_defaults(apps, schema_editor):
    SystemSettings = apps.get_model("systemsettings", "SystemSettings")
    SystemSettings.objects.filter(pk=1).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("systemsettings", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(seed_defaults, unseed_defaults),
    ]
