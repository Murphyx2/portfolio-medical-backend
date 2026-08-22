from django.db import migrations

# cedula_last4/nss_last4 are queried with __icontains from
# patient_ids_matching_digits() (apps/core/services.py) whenever a search
# term has 1-3 digits, so a substring match anywhere in the last 4 digits
# stays supported. A plain btree index (their existing db_index=True) can't
# serve a leading-wildcard LIKE, forcing a seq scan; a trigram GIN index
# makes that same query index-backed instead. Guarded to Postgres only
# (RunPython checks the vendor itself) since SQLite has no GIN/pg_trgm
# support - a no-op there, same pattern as 0008/0017.


def create_trgm_indexes(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    schema_editor.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    schema_editor.execute(
        "CREATE INDEX IF NOT EXISTS patients_cedula_last4_trgm_idx "
        "ON patients_patient USING gin (cedula_last4 gin_trgm_ops)"
    )
    schema_editor.execute(
        "CREATE INDEX IF NOT EXISTS patients_nss_last4_trgm_idx "
        "ON patients_patient USING gin (nss_last4 gin_trgm_ops)"
    )


def drop_trgm_indexes(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    schema_editor.execute("DROP INDEX IF EXISTS patients_cedula_last4_trgm_idx")
    schema_editor.execute("DROP INDEX IF EXISTS patients_nss_last4_trgm_idx")


class Migration(migrations.Migration):

    dependencies = [
        ("patients", "0018_backfill_patient_guardian_cedula_search_index"),
    ]

    operations = [
        migrations.RunPython(create_trgm_indexes, drop_trgm_indexes),
    ]
