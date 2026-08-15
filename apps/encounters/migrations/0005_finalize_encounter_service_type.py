import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('encounters', '0004_populate_encounter_service_type'),
    ]

    operations = [
        migrations.AlterField(
            model_name='encounter',
            name='service_type',
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name='encounters',
                to='services.servicetype',
            ),
        ),
        migrations.RemoveField(
            model_name='encounter',
            name='encounter_type',
        ),
        migrations.DeleteModel(
            name='EncounterType',
        ),
    ]
