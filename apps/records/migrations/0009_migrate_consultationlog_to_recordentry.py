"""Convert every ConsultationLog row into a COMPLETED RecordEntry on its
patient's MedicalRecord, preserving the clinical text (concatenated SOAP
sections) instead of silently dropping it when ConsultationLog is deleted
(a later migration). ConsultationLog itself isn't a "medical record" under
the non-hard-delete invariant, but its content still deserves to survive.

Runs after 0008's collapse, so each patient has at most one MedicalRecord;
a patient with logs but no MedicalRecord at all (possible if a
consultation-log was ever created via the API without the patient ever
getting the auto-created initial record) gets one created here, attributed
to the log's own doctor.
"""

from django.db import migrations


def convert(apps, schema_editor):
    ConsultationLog = apps.get_model("records", "ConsultationLog")
    MedicalRecord = apps.get_model("records", "MedicalRecord")
    RecordEntry = apps.get_model("records", "RecordEntry")

    for log in ConsultationLog.objects.order_by("date"):
        record = MedicalRecord.objects.filter(patient_id=log.patient_id).first()
        if record is None:
            record = MedicalRecord.objects.create(
                patient_id=log.patient_id,
                created_by_id=log.doctor_id,
                center_id=log.center_id,
            )
        parts = []
        if log.subjective:
            parts.append(f"S: {log.subjective}")
        if log.objective:
            parts.append(f"O: {log.objective}")
        if log.assessment:
            parts.append(f"A: {log.assessment}")
        if log.plan:
            parts.append(f"P: {log.plan}")
        if log.notes:
            parts.append(f"Notas: {log.notes}")
        RecordEntry.objects.create(
            record=record,
            author_id=log.doctor_id,
            status="COMPLETED",
            observaciones="\n".join(parts),
            completed_at=log.date,
        )


class Migration(migrations.Migration):

    dependencies = [
        ("records", "0008_collapse_medical_records"),
    ]

    operations = [
        migrations.RunPython(convert, migrations.RunPython.noop),
    ]
