from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("patients", "0022_backfill_patientguardian"),
    ]

    operations = [
        migrations.RemoveField(model_name="patient", name="guardian_cedula"),
        migrations.RemoveField(model_name="patient", name="guardian_cedula_hash"),
        migrations.RemoveField(model_name="patient", name="guardian_cedula_last4"),
        migrations.RemoveField(model_name="patient", name="guardian_first_name"),
        migrations.RemoveField(model_name="patient", name="guardian_last_name"),
        migrations.RemoveField(model_name="patient", name="guardian_nss"),
        migrations.RemoveField(model_name="patient", name="guardian_phone"),
    ]
