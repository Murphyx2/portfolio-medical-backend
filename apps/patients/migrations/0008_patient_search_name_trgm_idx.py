from django.db import migrations

# search_name is queried with __icontains from PatientSearchFilter and
# RecordSearchFilter on every name search; a trigram GIN index lets Postgres
# use an index scan for arbitrary substring matches instead of a seq scan
# (a plain btree index only helps prefix matches). Guarded to Postgres only
# (RunPython checks the vendor itself) because the test suite runs on
# SQLite, which has no GIN/pg_trgm support — this is a no-op there.
# Deliberately not mirrored in Patient.Meta.indexes: it's a database-only
# enhancement, not part of Django's model state.


def create_trgm_index(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    schema_editor.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    schema_editor.execute(
        "CREATE INDEX IF NOT EXISTS patients_search_name_trgm_idx "
        "ON patients_patient USING gin (search_name gin_trgm_ops)"
    )


def drop_trgm_index(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    schema_editor.execute("DROP INDEX IF EXISTS patients_search_name_trgm_idx")


class Migration(migrations.Migration):

    dependencies = [
        ("patients", "0007_backfill_patient_last4"),
    ]

    operations = [
        migrations.RunPython(create_trgm_index, drop_trgm_index),
    ]
