import apps.core.fields
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('patients', '0020_patientphonenumber'),
    ]

    operations = [
        migrations.CreateModel(
            name='PatientGuardian',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('first_name', apps.core.fields.EncryptedCharField()),
                ('last_name', apps.core.fields.EncryptedCharField()),
                ('cedula', apps.core.fields.EncryptedCharField(blank=True, default='')),
                ('nss', apps.core.fields.EncryptedCharField(blank=True, default='')),
                ('phone', apps.core.fields.EncryptedCharField(blank=True, default='')),
                ('cedula_last4', models.CharField(blank=True, db_index=True, max_length=4)),
                ('cedula_hash', models.CharField(blank=True, db_index=True, max_length=64)),
                ('patient', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='guardians', to='patients.patient')),
            ],
            options={
                'ordering': ['id'],
            },
        ),
    ]
