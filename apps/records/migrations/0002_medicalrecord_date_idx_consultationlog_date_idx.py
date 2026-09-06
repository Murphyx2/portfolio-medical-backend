from django.db import migrations, models


class Migration(migrations.Migration):
    """Both models default-order by ``-date`` (every list request), but
    neither column was indexed."""

    dependencies = [
        ("records", "0001_initial"),
    ]

    operations = [
        migrations.AddIndex(
            model_name="medicalrecord",
            index=models.Index(fields=["-date"], name="records_mr_date_idx"),
        ),
        migrations.AddIndex(
            model_name="consultationlog",
            index=models.Index(fields=["-date"], name="records_cl_date_idx"),
        ),
    ]
