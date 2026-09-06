import apps.core.fields
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('patients', '0023_remove_patient_guardian_fields'),
        ('records', '0006_seed_ap_catalog'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='RecordEntry',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('status', models.CharField(choices=[('DRAFT', 'Draft'), ('COMPLETED', 'Completed')], default='DRAFT', max_length=10)),
                ('ta_systolic', models.PositiveSmallIntegerField(blank=True, null=True)),
                ('ta_diastolic', models.PositiveSmallIntegerField(blank=True, null=True)),
                ('fc', models.PositiveSmallIntegerField(blank=True, null=True)),
                ('fr', models.PositiveSmallIntegerField(blank=True, null=True)),
                ('weight_lb', models.DecimalField(blank=True, decimal_places=1, max_digits=6, null=True)),
                ('height_cm', models.DecimalField(blank=True, decimal_places=1, max_digits=5, null=True)),
                ('talla_cm', models.DecimalField(blank=True, decimal_places=1, max_digits=5, null=True)),
                ('temperature_c', models.DecimalField(blank=True, decimal_places=1, max_digits=4, null=True)),
                ('glucose', models.PositiveSmallIntegerField(blank=True, null=True)),
                ('vitals_notes', models.CharField(blank=True, default='', max_length=500)),
                ('imc', models.DecimalField(blank=True, decimal_places=2, max_digits=5, null=True)),
                ('dx', apps.core.fields.EncryptedTextField(blank=True, default='')),
                ('tx', apps.core.fields.EncryptedTextField(blank=True, default='')),
                ('observaciones', apps.core.fields.EncryptedTextField(blank=True, default='')),
                ('personal_ap_snapshot', models.JSONField(blank=True, default=list)),
                ('family_ap_snapshot', models.JSONField(blank=True, default=list)),
                ('completed_at', models.DateTimeField(blank=True, null=True)),
                ('author', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='record_entries', to=settings.AUTH_USER_MODEL)),
                ('record', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='entries', to='records.medicalrecord')),
            ],
            options={
                'ordering': ['-completed_at', '-created_at'],
            },
        ),
        migrations.AddIndex(
            model_name='recordentry',
            index=models.Index(fields=['record', 'status', '-completed_at'], name='records_entry_status_idx'),
        ),
        migrations.AddConstraint(
            model_name='recordentry',
            constraint=models.UniqueConstraint(condition=models.Q(('status', 'DRAFT')), fields=('record', 'author'), name='uniq_draft_per_record_author'),
        ),
        migrations.CreateModel(
            name='RecordPersonalCondition',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('custom_label', models.CharField(blank=True, default='', max_length=255)),
                ('is_custom', models.BooleanField(default=False)),
                ('ap_type', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='+', to='records.aptype')),
                ('record', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='personal_conditions', to='records.medicalrecord')),
            ],
            options={
                'ordering': ['id'],
            },
        ),
        migrations.AddConstraint(
            model_name='recordpersonalcondition',
            constraint=models.UniqueConstraint(condition=models.Q(('ap_type__isnull', False)), fields=('record', 'ap_type'), name='uniq_record_personal_ap_type'),
        ),
        migrations.CreateModel(
            name='RecordFamilyCondition',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('relationship', models.CharField(choices=[('MADRE', 'Madre'), ('PADRE', 'Padre'), ('HERMANA', 'Hermana'), ('HERMANO', 'Hermano'), ('HIJA', 'Hija'), ('HIJO', 'Hijo'), ('ABUELA', 'Abuela'), ('ABUELO', 'Abuelo'), ('TIA', 'Tía'), ('TIO', 'Tío'), ('OTRO', 'Otro familiar')], max_length=10)),
                ('relationship_other', models.CharField(blank=True, default='', max_length=100)),
                ('relative_name', models.CharField(blank=True, default='', max_length=200)),
                ('custom_label', models.CharField(blank=True, default='', max_length=255)),
                ('is_custom', models.BooleanField(default=False)),
                ('ap_type', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='+', to='records.aptype')),
                ('record', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='family_conditions', to='records.medicalrecord')),
                ('related_patient', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='+', to='patients.patient')),
            ],
            options={
                'ordering': ['id'],
            },
        ),
    ]
