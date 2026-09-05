from django.db import migrations


def seed(apps, schema_editor):
    ReportDefinition = apps.get_model("reportes", "ReportDefinition")
    ReportPack = apps.get_model("reportes", "ReportPack")
    ReportDefinition.objects.get_or_create(
        engine_key="servicios_prestados",
        defaults={
            "name": "Servicios prestados",
            "category": "Servicios",
            "description": "Cantidad y co-pago por servicio, un ARS y programa",
        },
    )
    ReportPack.objects.get_or_create(
        engine_key="paquete_ars",
        defaults={
            "name": "Paquete ARS",
            "periodicity": "MENSUAL",
        },
    )


def unseed(apps, schema_editor):
    ReportDefinition = apps.get_model("reportes", "ReportDefinition")
    ReportPack = apps.get_model("reportes", "ReportPack")
    ReportDefinition.objects.filter(engine_key="servicios_prestados").delete()
    ReportPack.objects.filter(engine_key="paquete_ars").delete()


class Migration(migrations.Migration):

    dependencies = [
        ("reportes", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(seed, unseed),
    ]
