"""Security fix (H-03): IT users no longer get Django admin (staff) access."""

from django.db import migrations


def revoke_it_staff(apps, schema_editor):
    User = apps.get_model("accounts", "User")
    User.objects.filter(role="IT").update(is_staff=False, is_superuser=False)


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(revoke_it_staff, migrations.RunPython.noop),
    ]
