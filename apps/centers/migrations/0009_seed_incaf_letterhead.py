# Demo-branch note: this originally seeded a specific real clinic's legal
# name/RNC/address/logo onto its letterhead fields. On this branch it fills
# in clearly-fake placeholder values for the generic demo center instead --
# no real business identity or logo image ships in this branch's history.

from django.db import migrations


def seed_demo_letterhead(apps, schema_editor):
    # No-op wherever no code="DEMO" center exists (e.g. test databases).
    # Only fills fields that are still blank/placeholder, so a value an
    # admin already customized through the Centers page is never
    # overwritten.
    MedicalCenter = apps.get_model("centers", "MedicalCenter")
    center = MedicalCenter.objects.filter(code="DEMO").first()
    if not center:
        return

    changed = []
    if not center.nombre_legal:
        center.nombre_legal = "Demo Medical Center, Inc."
        changed.append("nombre_legal")
    if not center.nombre_corto:
        center.nombre_corto = center.code
        changed.append("nombre_corto")
    if not center.rnc:
        center.rnc = "000000000"
        changed.append("rnc")

    if changed:
        center.save(update_fields=changed)


class Migration(migrations.Migration):

    dependencies = [
        ("centers", "0008_backfill_center_phones_emails"),
    ]

    operations = [
        migrations.RunPython(seed_demo_letterhead, migrations.RunPython.noop),
    ]
