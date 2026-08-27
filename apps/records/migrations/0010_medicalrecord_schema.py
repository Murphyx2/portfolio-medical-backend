from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("records", "0009_migrate_consultationlog_to_recordentry"),
    ]

    operations = [
        migrations.AlterModelOptions(
            name='medicalrecord',
            options={'ordering': ['-last_visit_at', '-created_at']},
        ),
        migrations.RemoveIndex(
            model_name='medicalrecord',
            name='records_mr_date_idx',
        ),
        migrations.RemoveField(model_name='medicalrecord', name='date'),
        migrations.RemoveField(model_name='medicalrecord', name='diagnosis'),
        migrations.RemoveField(model_name='medicalrecord', name='medicine_and_doses'),
        migrations.RemoveField(model_name='medicalrecord', name='notes'),
        migrations.RemoveField(model_name='medicalrecord', name='title'),
        migrations.RemoveField(model_name='medicalrecord', name='treatment'),
        migrations.AddField(
            model_name='medicalrecord', name='last_fc',
            field=models.PositiveSmallIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='medicalrecord', name='last_fc_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='medicalrecord', name='last_fr',
            field=models.PositiveSmallIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='medicalrecord', name='last_fr_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='medicalrecord', name='last_glucose',
            field=models.PositiveSmallIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='medicalrecord', name='last_glucose_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='medicalrecord', name='last_height_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='medicalrecord', name='last_height_cm',
            field=models.DecimalField(blank=True, decimal_places=1, max_digits=5, null=True),
        ),
        migrations.AddField(
            model_name='medicalrecord', name='last_imc',
            field=models.DecimalField(blank=True, decimal_places=2, max_digits=5, null=True),
        ),
        migrations.AddField(
            model_name='medicalrecord', name='last_imc_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='medicalrecord', name='last_ta_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='medicalrecord', name='last_ta_diastolic',
            field=models.PositiveSmallIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='medicalrecord', name='last_ta_systolic',
            field=models.PositiveSmallIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='medicalrecord', name='last_visit_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='medicalrecord', name='last_weight_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='medicalrecord', name='last_weight_lb',
            field=models.DecimalField(blank=True, decimal_places=1, max_digits=6, null=True),
        ),
    ]
