from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("records", "0011_medicalrecord_constraints"),
    ]

    operations = [
        migrations.DeleteModel(
            name='ConsultationLog',
        ),
    ]
