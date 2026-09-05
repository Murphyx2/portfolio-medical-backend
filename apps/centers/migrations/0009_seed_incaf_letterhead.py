from pathlib import Path

from django.core.files import File
from django.db import migrations

LOGO_PATH = Path(__file__).resolve().parent.parent / "seed_data" / "incaf_logo.jpg"


def seed_incaf_letterhead(apps, schema_editor):
    # No-op wherever no code="INCAF" center exists (e.g. test databases,
    # fresh installs before the clinic's center is created) -- same
    # precedent as 0005_set_incaf_as_default. Only fills fields that are
    # still blank/placeholder, so a value an admin already customized
    # through the Centers page is never overwritten.
    MedicalCenter = apps.get_model("centers", "MedicalCenter")
    center = MedicalCenter.objects.filter(code="INCAF").first()
    if not center:
        return

    changed = []
    if not center.nombre_legal:
        center.nombre_legal = "Instituto Cristiano de Atención a la Familia"
        changed.append("nombre_legal")
    if not center.nombre_corto:
        center.nombre_corto = center.code
        changed.append("nombre_corto")
    if not center.rnc:
        center.rnc = "130986012"
        changed.append("rnc")
    if not center.address or center.address == "Azua, RD":
        center.address = "C/Tortuguero NO 58 Azua. Rep.Dom."
        changed.append("address")
    if not center.logo and LOGO_PATH.exists():
        with open(LOGO_PATH, "rb") as f:
            center.logo.save("incaf_logo.jpg", File(f), save=False)
        changed.append("logo")

    if changed:
        center.save(update_fields=changed)


class Migration(migrations.Migration):

    dependencies = [
        ("centers", "0008_backfill_center_phones_emails"),
    ]

    operations = [
        migrations.RunPython(seed_incaf_letterhead, migrations.RunPython.noop),
    ]
