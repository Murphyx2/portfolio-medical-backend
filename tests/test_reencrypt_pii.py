"""python manage.py reencrypt_pii must also refresh the cedula_hash/nss_hash
blind index, not just the encrypted cedula/nss columns.

The blind-index key is derived from PII_FIELD_KEY, so it rotates whenever
PII_FIELD_KEY does; skipping the hash update on rotation would silently
strand every pre-rotation patient's hash under the old key, breaking
full-number search until each patient is individually re-saved.
"""

from cryptography.fernet import Fernet
from django.core.management import call_command
from django.test import override_settings

import apps.core.encryption as encryption
from apps.core.encryption import blind_index_digits
from apps.core.services import patient_ids_matching_digits
from apps.patients.models import Patient


def test_reencrypt_pii_updates_hash_columns_on_key_rotation(db):
    old_key = Fernet.generate_key().decode()
    new_key = Fernet.generate_key().decode()

    with override_settings(PII_FIELD_KEY=old_key):
        encryption._cipher = None
        patient = Patient.objects.create(
            first_name="Rota", last_name="Cion", cedula="00112345678", nss="98765432109"
        )
        old_cedula_hash = patient.cedula_hash
        old_nss_hash = patient.nss_hash
        assert old_cedula_hash == blind_index_digits("00112345678")

    with override_settings(PII_FIELD_KEY=new_key):
        encryption._cipher = None
        call_command("reencrypt_pii", old_key=old_key)

        patient.refresh_from_db()
        new_cedula_hash = blind_index_digits("00112345678")
        new_nss_hash = blind_index_digits("98765432109")

        assert patient.cedula_hash == new_cedula_hash
        assert patient.nss_hash == new_nss_hash
        # The derivation key changed, so the hash itself must have changed too.
        assert new_cedula_hash != old_cedula_hash
        assert new_nss_hash != old_nss_hash

        # Full-number search still finds the patient immediately after rotation.
        assert patient.id in list(patient_ids_matching_digits("00112345678"))


def test_reencrypt_pii_updates_guardian_cedula_hash_on_key_rotation(db):
    """Regression test for a real pre-existing bug: reencrypt_pii used to
    hard-code `if name in ("cedula", "nss")`, so guardian_cedula_hash was
    never recomputed on key rotation and silently went stale. Now it reads
    from Patient.PII_INDEX_FIELDS (the same mapping Patient.save() uses),
    so guardian_cedula is covered too."""
    old_key = Fernet.generate_key().decode()
    new_key = Fernet.generate_key().decode()

    with override_settings(PII_FIELD_KEY=old_key):
        encryption._cipher = None
        patient = Patient.objects.create(
            first_name="Kid",
            last_name="One",
            cedula="",
            has_guardian=True,
            guardian_cedula="00198765432",
            guardian_first_name="Parent",
            guardian_last_name="One",
        )
        old_guardian_hash = patient.guardian_cedula_hash
        assert old_guardian_hash == blind_index_digits("00198765432")

    with override_settings(PII_FIELD_KEY=new_key):
        encryption._cipher = None
        call_command("reencrypt_pii", old_key=old_key)

        patient.refresh_from_db()
        new_guardian_hash = blind_index_digits("00198765432")

        assert patient.guardian_cedula_hash == new_guardian_hash
        assert new_guardian_hash != old_guardian_hash

        # Guardian-cedula search still finds the patient immediately after rotation.
        assert patient.id in list(
            patient_ids_matching_digits("00198765432", include_guardian=True)
        )
