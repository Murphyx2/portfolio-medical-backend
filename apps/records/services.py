"""Service-layer functions for the records app, callable from other apps
without those apps reaching into apps.records.models directly (the
modular-monolith convention: cross-app writes go through a service/serializer
call, not a raw model import)."""

from decimal import ROUND_HALF_UP, Decimal

from django.db import transaction

from apps.core.services import client_ip, log_audit
from apps.patients.models import Patient

_LB_PER_KG = Decimal("0.453592")


def compute_imc(weight_lb, height_cm) -> Decimal:
    """Spec §10's formula, stored at 2 decimals (displayed at 1):
    weightKg = pesoLb * 0.453592; heightM = estaturaCm / 100;
    imc = weightKg / heightM**2."""
    weight_kg = Decimal(weight_lb) * _LB_PER_KG
    height_m = Decimal(height_cm) / Decimal(100)
    imc = weight_kg / (height_m * height_m)
    return imc.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def create_initial_record(patient: Patient, user, *, request=None) -> "MedicalRecord":
    """Every new patient gets the one living expediente (MedicalRecord) right
    away, so Records.tsx always has something to open for them (see the
    ?patient= auto-open flow from Encounters.tsx) instead of an empty
    history -- left for a doctor/nurse to fill in with a first RecordEntry
    during the patient's first real visit. The patient's own allergies/
    critical_conditions already live on Patient itself (rendered in the
    chart's snapshot header directly from there) so nothing needs
    duplicating onto the anchor row.

    Audited like any other create (previously this bypassed AuditMixin
    entirely since it was a raw model .create() call inside
    PatientViewSet.perform_create, with no corresponding AuditLog row).
    """
    from apps.records.models import MedicalRecord

    with transaction.atomic():
        record = MedicalRecord.objects.create(
            patient=patient,
            created_by=user,
            center=patient.center,
        )
        log_audit(
            user=user,
            action="CREATE",
            target=record,
            ip_address=client_ip(request) if request else None,
        )
    return record
