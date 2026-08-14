from django.db import migrations

# Vacunación/Chequeo de rutina/Laboratorio don't require a primary diagnosis
# to admit -- routine, non-diagnostic visit types.
ENCOUNTER_TYPES = {
    "Consulta General": True,
    "Emergencia": True,
    "Seguimiento": True,
    "Procedimiento": True,
    "Vacunación": False,
    "Chequeo de rutina": False,
    "Laboratorio": False,
}


def seed_encounter_types(apps, schema_editor):
    EncounterType = apps.get_model("encounters", "EncounterType")
    for name, requires_diagnosis in ENCOUNTER_TYPES.items():
        EncounterType.objects.get_or_create(
            name=name, defaults={"requires_diagnosis": requires_diagnosis}
        )


class Migration(migrations.Migration):

    dependencies = [
        ('encounters', '0001_initial'),
    ]

    operations = [
        migrations.RunPython(seed_encounter_types, migrations.RunPython.noop),
    ]
