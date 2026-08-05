from django.db import migrations


def seed_ars(apps, schema_editor):
    ARS = apps.get_model("ars", "ARS")
    ARSProgram = apps.get_model("ars", "ARSProgram")
    seeds = [
        ("SM", "SEMMA", ["P Y P SEMMA"]),
        ("SE", "SENASA", ["SENASA Contigo"]),
    ]
    for ars_id, name, programs in seeds:
        ars, _ = ARS.objects.get_or_create(ars_id=ars_id, defaults={"name": name})
        ars.name = name
        ars.save()
        for program in programs:
            ARSProgram.objects.get_or_create(ars=ars, name=program)


class Migration(migrations.Migration):
    dependencies = [
        ("ars", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(seed_ars, migrations.RunPython.noop),
    ]
