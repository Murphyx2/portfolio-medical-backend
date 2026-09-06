# Best-effort data migration: regex-parses existing free-text
# `concentration` strings (e.g. "50mg", "100UI/ml") into the new structured
# concentracion_valor/concentracion_unidad fields where the pattern cleanly
# matches one of the known unit choices. Left blank (no error) where it
# doesn't parse cleanly -- this is explicitly best-effort, not a robust
# parser (see RECETAS_REQUIREMENTS.md §3).

import re

from django.db import migrations

# Longest units first so e.g. "50mg/ml" isn't mis-split as "mg" + "/ml".
_UNIT_PATTERN = re.compile(
    r"^\s*(\d+(?:\.\d+)?)\s*(mg/ml|ui/ml|mcg|mg|ml|ui|g|%)\s*$",
    re.IGNORECASE,
)

# Case-insensitive-match -> canonical ConcentracionUnidad value.
_UNIT_MAP = {
    "mg/ml": "mg/ml",
    "ui/ml": "UI/ml",
    "mcg": "mcg",
    "mg": "mg",
    "ml": "ml",
    "ui": "UI",
    "g": "g",
    "%": "%",
}


def backfill_concentracion(apps, schema_editor):
    Medicine = apps.get_model("medicines", "Medicine")
    for medicine in Medicine.objects.exclude(concentration=""):
        match = _UNIT_PATTERN.match(medicine.concentration or "")
        if not match:
            continue
        valor, unidad_raw = match.groups()
        unidad = _UNIT_MAP.get(unidad_raw.lower())
        if not unidad:
            continue
        medicine.concentracion_valor = valor
        medicine.concentracion_unidad = unidad
        medicine.save(update_fields=["concentracion_valor", "concentracion_unidad"])


class Migration(migrations.Migration):

    dependencies = [
        ("medicines", "0003_medicine_concentracion_unidad_and_more"),
    ]

    operations = [
        migrations.RunPython(backfill_concentracion, migrations.RunPython.noop),
    ]
