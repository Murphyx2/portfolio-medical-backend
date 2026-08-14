from django.db import migrations

# Matches the Spanish labels already shown in the UI for each legacy enum key
# (frontend/src/i18n/es.json rooms.type*), so converting to a free-form
# RoomType catalog is a visual no-op for existing data.
LEGACY_LABELS = {
    "CONSULTATION": "Consulta",
    "PROCEDURE": "Procedimiento",
    "LABORATORY": "Laboratorio",
    "IMAGING": "Imágenes",
    "WAITING": "Sala de espera",
    "OTHER": "Otro",
}


def seed_room_types(apps, schema_editor):
    RoomType = apps.get_model("rooms", "RoomType")
    for name in LEGACY_LABELS.values():
        RoomType.objects.get_or_create(name=name)


class Migration(migrations.Migration):

    dependencies = [
        ('rooms', '0002_roomtype'),
    ]

    operations = [
        migrations.RunPython(seed_room_types, migrations.RunPython.noop),
    ]
