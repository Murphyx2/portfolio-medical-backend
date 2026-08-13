from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('patients', '0009_patient_active'),
    ]

    operations = [
        migrations.AddField(
            model_name='patient',
            name='cedula_hash',
            field=models.CharField(blank=True, db_index=True, max_length=64),
        ),
        migrations.AddField(
            model_name='patient',
            name='nss_hash',
            field=models.CharField(blank=True, db_index=True, max_length=64),
        ),
    ]
