# Adds the search_name index in its own transaction, after the
# encrypt_patient_names data migration (0004) has committed (Postgres rejects
# CREATE INDEX on a table with pending trigger events from prior ALTER/UPDATE
# in the same transaction).
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('patients', '0004_encrypt_patient_names'),
    ]

    operations = [
        migrations.AddIndex(
            model_name='patient',
            index=models.Index(fields=['search_name'], name='patients_pa_search__c624f0_idx'),
        ),
    ]
