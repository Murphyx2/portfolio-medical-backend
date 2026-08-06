"""Security fix (F2): is_staff/is_superuser are now derived from role.

Every non-ADMIN account (including demoted admins and any row left
inconsistent before the User.save() change) must have is_staff=False and
is_superuser=False so Django admin (which exposes decrypted PII) is reachable
only by the single ADMIN role.
"""

from django.db import migrations


def derive_flags_from_role(apps, schema_editor):
    User = apps.get_model("accounts", "User")
    User.objects.filter(role="ADMIN").update(is_staff=True, is_superuser=True)
    User.objects.exclude(role="ADMIN").update(is_staff=False, is_superuser=False)


def undo(apps, schema_editor):
    # Nothing to restore: the previous behavior left the flags as they were,
    # which is exactly the inconsistent state this migration repairs.
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0002_revoke_it_staff"),
    ]

    operations = [
        migrations.RunPython(derive_flags_from_role, undo),
    ]
