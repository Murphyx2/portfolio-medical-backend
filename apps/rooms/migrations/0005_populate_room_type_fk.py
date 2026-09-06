from django.db import migrations

LEGACY_LABELS = {
    "CONSULTATION": "Consulta",
    "PROCEDURE": "Procedimiento",
    "LABORATORY": "Laboratorio",
    "IMAGING": "Imágenes",
    "WAITING": "Sala de espera",
    "OTHER": "Otro",
}


def populate_room_type_fk(apps, schema_editor):
    Room = apps.get_model("rooms", "Room")
    RoomType = apps.get_model("rooms", "RoomType")
    types_by_name = {rt.name: rt for rt in RoomType.objects.all()}
    for room in Room.objects.all():
        label = LEGACY_LABELS.get(room.room_type, LEGACY_LABELS["OTHER"])
        room.room_type_fk = types_by_name[label]
        room.save(update_fields=["room_type_fk"])


class Migration(migrations.Migration):

    dependencies = [
        ('rooms', '0004_room_room_type_fk_temp'),
    ]

    operations = [
        migrations.RunPython(populate_room_type_fk, migrations.RunPython.noop),
    ]
