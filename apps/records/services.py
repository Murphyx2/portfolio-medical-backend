"""Service-layer functions for the records app, callable from other apps
without those apps reaching into apps.records.models directly (the
modular-monolith convention: cross-app writes go through a service/serializer
call, not a raw model import)."""

from django.db import transaction

from apps.core.services import client_ip, log_audit
from apps.patients.models import Patient


def create_initial_record(patient: Patient, user, *, request=None) -> "MedicalRecord":
    """Every new patient gets a placeholder medical record right away, so
    Records.tsx always has something to open for them (see the ?patient=
    auto-open flow from Encounters.tsx) instead of an empty history. Left
    for a doctor/nurse to fill in during the patient's first real visit --
    no clinical fields are guessed here, only the safety-relevant summary
    already captured on the patient form.

    Audited like any other create (previously this bypassed AuditMixin
    entirely since it was a raw model .create() call inside
    PatientViewSet.perform_create, with no corresponding AuditLog row).
    """
    from apps.records.models import MedicalRecord

    notes_parts = []
    if patient.allergies:
        notes_parts.append(f"Alergias: {patient.allergies}")
    if patient.critical_conditions:
        notes_parts.append(f"Condiciones críticas: {patient.critical_conditions}")

    with transaction.atomic():
        record = MedicalRecord.objects.create(
            patient=patient,
            created_by=user,
            center=patient.center,
            title="Registro inicial",
            notes="\n".join(notes_parts),
        )
        log_audit(
            user=user,
            action="CREATE",
            target=record,
            ip_address=client_ip(request) if request else None,
        )
    return record
