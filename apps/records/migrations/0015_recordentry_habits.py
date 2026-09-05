from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("records", "0014_aptype_ordering_by_category"),
    ]

    operations = [
        migrations.AddField(
            model_name="recordentry",
            name="habits",
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.AddField(
            model_name="recordentry",
            name="habits_notes",
            field=models.CharField(blank=True, default="", max_length=1000),
        ),
        migrations.AddField(
            model_name="medicalrecord",
            name="habits_snapshot",
            field=models.JSONField(blank=True, default=dict),
        ),
    ]
