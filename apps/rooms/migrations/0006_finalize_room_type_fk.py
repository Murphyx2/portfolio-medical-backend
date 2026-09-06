import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('rooms', '0005_populate_room_type_fk'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='room',
            name='room_type',
        ),
        migrations.RenameField(
            model_name='room',
            old_name='room_type_fk',
            new_name='room_type',
        ),
        migrations.AlterField(
            model_name='room',
            name='room_type',
            field=models.ForeignKey(
                to='rooms.roomtype',
                on_delete=django.db.models.deletion.PROTECT,
                related_name='rooms',
            ),
        ),
    ]
