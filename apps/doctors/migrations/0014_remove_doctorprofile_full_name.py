from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('doctors', '0013_backfill_doctorprofile_first_last_name'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='doctorprofile',
            name='full_name',
        ),
    ]
