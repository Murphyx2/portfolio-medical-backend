"""Service-layer functions for the patients app, callable from other apps
without those apps reaching into apps.patients.models directly (the
modular-monolith convention: cross-app writes go through a service/serializer
call, not a raw model import)."""

from apps.patients.models import Patient


def find_whatsapp_optin_patient_by_phone(local_10: str) -> Patient | None:
    """Patient.phone is a Fernet-encrypted column (non-deterministic
    ciphertext) -- an exact DB-level filter isn't possible without a blind
    index, so this scans only opt-in patients (small, bounded set) and
    compares the transparently-decrypted value in Python. `local_10` is
    the last 10 digits of an inbound WhatsApp sender number."""
    return next(
        (p for p in Patient.objects.filter(whatsapp_opt_in=True) if p.phone == local_10),
        None,
    )


def opt_out_patient_whatsapp(patient: Patient) -> None:
    """Flips whatsapp_opt_in off in response to an inbound STOP/SALIR/NO/
    CANCELAR keyword (see apps.communications.views._apply_inbound_message).
    Only the one field changes -- no other patient state is touched."""
    patient.whatsapp_opt_in = False
    patient.save(update_fields=["whatsapp_opt_in"])
