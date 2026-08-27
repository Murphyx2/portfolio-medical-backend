"""Seed the AP (Antecedentes Patologicos) catalog -- Requirements/
EXPEDIENTES_MEDICOS_AI_SPEC.md section 9. get_or_create everywhere so this is
safe to run more than once (fresh installs vs. an environment that already
has some of these rows from a partial run) and never duplicates on re-run.
"""

from django.db import migrations

CATALOG = [
    ("Sistema Cardiovascular", [
        "Hipertensión Arterial (HTA)",
        "Insuficiencia Cardíaca",
        "Cardiopatía Isquémica / Infarto de Miocardio",
        "Arritmias (ej. Fibrilación Auricular)",
        "Enfermedad Vascular Periférica / Varices",
    ]),
    ("Sistema Respiratorio", [
        "Asma Bronquial",
        "EPOC (Enfermedad Pulmonar Obstructiva Crónica)",
        "Sinusitis Crónica / Rinitis Alérgica",
        "Tuberculosis (TB)",
        "Apnea del Sueño",
    ]),
    ("Sistema Endocrino y Metabólico", [
        "Diabetes Mellitus Tipo 1 / Tipo 2",
        "Dislipidemia (Colesterol / Triglicéridos elevados)",
        "Hipotiroidismo / Hipertiroidismo",
        "Obesidad",
        "Síndrome de Ovario Poliquístico (SOP)",
    ]),
    ("Sistema Gastrointestinal", [
        "Gastritis / Enfermedad por Reflujo Gastroesofágico (ERGE)",
        "Úlcera Péptica",
        "Síndrome de Intestino Irritable / Colitis",
        "Cirrosis / Hígado Graso",
        "Hemorroides / Enfermedad Diverticular",
    ]),
    ("Sistema Genitourinario", [
        "Infección de Vías Urinarias Recurrente",
        "Litiasis Renal (Cálculos)",
        "Insuficiencia Renal Crónica",
        "Hiperplasia Benigna de Próstata",
    ]),
    ("Sistema Neurológico y Psiquiátrico", [
        "Migraña / Cefalea Crónica",
        "Epilepsia / Convulsiones",
        "Accidente Cerebrovascular (ACV / Ictus)",
        "Trastorno de Ansiedad / Depresión",
        "Insomnio",
        "Enfermedades Neurodegenerativas (Alzheimer / Parkinson)",
    ]),
    ("Sistema Musculoesquelético y Reumatológico", [
        "Osteoartritis / Artrosis",
        "Artritis Reumatoide / Gota",
        "Osteoporosis",
        "Lumbalgia Crónica",
    ]),
    ("Alergias e Inmunología", [
        "Alergia Alimentaria",
        "Alergia a Medicamentos (ej. Penicilina, AINEs)",
        "Alergias Ambientales / Rinitis",
        "Enfermedades Autoinmunes (ej. Lupus)",
    ]),
    ("Oncología", [
        "Cáncer de Mama / Cérvix",
        "Cáncer de Próstata",
        "Cáncer Colorrectal",
        "Cáncer de Pulmón",
    ]),
]


def seed(apps, schema_editor):
    APCategory = apps.get_model("records", "APCategory")
    APType = apps.get_model("records", "APType")
    for cat_order, (cat_name, types) in enumerate(CATALOG):
        category, _ = APCategory.objects.get_or_create(
            name=cat_name, defaults={"sort_order": cat_order}
        )
        for type_order, type_name in enumerate(types):
            APType.objects.get_or_create(
                category=category, name=type_name, defaults={"sort_order": type_order}
            )


class Migration(migrations.Migration):

    dependencies = [
        ("records", "0005_apcategory_aptype"),
    ]

    operations = [
        migrations.RunPython(seed, migrations.RunPython.noop),
    ]
