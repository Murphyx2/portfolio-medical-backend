"""Collapse MedicalRecord down to at most one row per patient, ahead of the
uniq_active_medicalrecord_patient constraint (added in a later migration).

Today's MedicalRecord allows many rows per patient (one per doctor visit);
the Expedientes Médicos refactor makes it the one-per-patient chart anchor,
with per-visit content moving to RecordEntry. For each patient with more
than one MedicalRecord, this keeps the most-recently-created row as the
survivor, reparents the losers' RecordImages onto it (so uploaded images
aren't lost), and hard-deletes the loser rows.

DELIBERATE DATA-LOSS STEP: this is safe only because the hosted data at the
time of writing is documented as disposable test/demo data (see
infra/PROGRESS.md's "Information-handling summary"). Before ever running
this against an environment with real patient data, re-scope this migration
to a lossless merge (e.g. one RecordEntry per collapsed row's old
diagnosis/treatment/notes) instead of a straight keep-newest-delete-rest.
"""

from django.db import migrations
from django.db.models import Count


def collapse(apps, schema_editor):
    MedicalRecord = apps.get_model("records", "MedicalRecord")
    RecordImage = apps.get_model("records", "RecordImage")

    patient_ids = (
        MedicalRecord.objects.values("patient_id")
        .annotate(n=Count("id"))
        .filter(n__gt=1)
        .values_list("patient_id", flat=True)
    )
    for patient_id in patient_ids:
        records = list(
            MedicalRecord.objects.filter(patient_id=patient_id).order_by("-created_at", "-id")
        )
        survivor, losers = records[0], records[1:]
        loser_ids = [r.id for r in losers]
        RecordImage.objects.filter(record_id__in=loser_ids).update(record_id=survivor.id)
        MedicalRecord.objects.filter(id__in=loser_ids).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("records", "0007_recordentry_conditions"),
    ]

    operations = [
        migrations.RunPython(collapse, migrations.RunPython.noop),
    ]
