from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("records", "0010_medicalrecord_schema"),
    ]

    operations = [
        migrations.AddIndex(
            model_name='medicalrecord',
            index=models.Index(fields=['-last_visit_at'], name='records_mr_last_visit_idx'),
        ),
        migrations.AddConstraint(
            model_name='medicalrecord',
            constraint=models.UniqueConstraint(
                condition=models.Q(('active', True)),
                fields=('patient',),
                name='uniq_active_medicalrecord_patient',
            ),
        ),
    ]
