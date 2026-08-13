from django.db import migrations


def seed_service_types(apps, schema_editor):
    ServiceType = apps.get_model("services", "ServiceType")
    for name in ("Admission", "Vaccination", "Emergency"):
        ServiceType.objects.get_or_create(name=name)


class Migration(migrations.Migration):
    dependencies = [
        ("services", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(seed_service_types, migrations.RunPython.noop),
    ]
