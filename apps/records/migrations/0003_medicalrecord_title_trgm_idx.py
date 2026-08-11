from django.db import migrations

# title is queried with __icontains from RecordSearchFilter on every record
# search. Same rationale/guard as patients/migrations/0008 (trigram GIN
# instead of btree for substring matches; Postgres-only, no-op on the
# SQLite test backend; not mirrored in MedicalRecord.Meta.indexes).


def create_trgm_index(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    schema_editor.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    schema_editor.execute(
        "CREATE INDEX IF NOT EXISTS records_title_trgm_idx "
        "ON records_medicalrecord USING gin (title gin_trgm_ops)"
    )


def drop_trgm_index(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    schema_editor.execute("DROP INDEX IF EXISTS records_title_trgm_idx")


class Migration(migrations.Migration):

    dependencies = [
        ("records", "0002_medicalrecord_date_idx_consultationlog_date_idx"),
    ]

    operations = [
        migrations.RunPython(create_trgm_index, drop_trgm_index),
    ]
