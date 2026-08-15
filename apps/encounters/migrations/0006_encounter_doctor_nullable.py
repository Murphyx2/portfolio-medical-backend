import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('encounters', '0005_finalize_encounter_service_type'),
    ]

    operations = [
        migrations.AlterField(
            model_name='encounter',
            name='doctor',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name='encounters',
                to='doctors.doctorprofile',
            ),
        ),
    ]
