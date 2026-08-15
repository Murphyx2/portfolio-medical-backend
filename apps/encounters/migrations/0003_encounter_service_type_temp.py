import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('encounters', '0002_seed_encounter_types'),
        ('services', '0003_servicetype_requires_doctor_diagnosis'),
    ]

    operations = [
        migrations.AddField(
            model_name='encounter',
            name='service_type',
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name='encounters',
                to='services.servicetype',
            ),
        ),
    ]
