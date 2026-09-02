from django.db import migrations


def backfill_co_pago(apps, schema_editor):
    """Adopt today's flat co_pago/privado value as history for every
    EncounterService row that predates ServicePrice -- ServicePrice starts
    empty, so this is exactly what apps.services.services.resolve_line_price
    would have returned for each row at this point in time. Reads directly
    from the historical model state (no ServicePrice rows can exist yet),
    so no need to import the real resolve_line_price helper here."""
    EncounterService = apps.get_model("encounters", "EncounterService")
    qs = EncounterService.objects.filter(co_pago__isnull=True).select_related(
        "service", "encounter"
    )
    for line in qs.iterator():
        if line.ars_covered and line.encounter.ars_id is not None:
            line.co_pago = line.service.co_pago
        else:
            line.co_pago = line.service.privado
        line.save(update_fields=["co_pago"])


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("encounters", "0012_encounterservice_co_pago"),
        ("services", "0005_serviceprice"),
    ]

    operations = [
        migrations.RunPython(backfill_co_pago, noop_reverse),
    ]
