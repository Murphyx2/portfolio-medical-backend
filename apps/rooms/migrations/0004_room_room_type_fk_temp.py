import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('rooms', '0003_seed_room_types'),
    ]

    operations = [
        migrations.AddField(
            model_name='room',
            name='room_type_fk',
            field=models.ForeignKey(
                to='rooms.roomtype',
                on_delete=django.db.models.deletion.PROTECT,
                null=True,
                related_name='rooms_tmp',
            ),
        ),
    ]
