"""Regression tests for the cedula digits-only change (backend commit 0eda59d).

Spec (from the shipped change): "Cedula is now stored digits-only (exactly 11
digits enforced; hyphens are frontend display-only). Backend validates/strips
non-digits in serializers.py validate_cedula."

Existing coverage in test_ars_patient_insurance.py:
- 10-digit and 12-digit cedulas rejected (400)
- POST with hyphenated cedula stored digits-only ("010-0108492-0" -> "01001084920")

This file adds the missing edges:
- PATCH (partial update) with hyphenated cedula -> digits-only stored
- Plain 11-digit input (no hyphens) accepted unchanged
- Mixed non-digit junk (spaces/hyphens) stripped as long as 11 digits remain
- Garbage with < 11 digits rejected
- Database-level round trip: value stored in the DB decrypts to digits-only
"""

import pytest

from django.db import connection

from apps.core.encryption import is_encrypted
from apps.patients.models import Patient

HYPHENATED = "010-0108492-0"
DIGITS = "01001084920"


def _payload(**overrides):
    data = {
        "first_name": "Ced",
        "last_name": "Test",
        "birth_date": "1990-05-12",
        "gender": "FEMALE",
        "phone": "8095550100",
        "email": "ced@example.com",
    }
    data.update(overrides)
    return data


def test_plain_11_digit_cedula_accepted_unchanged(auth_client, receptionist_user):
    res = auth_client(receptionist_user).post(
        "/api/patients/", _payload(cedula=DIGITS), format="json"
    )
    assert res.status_code == 201, res.data
    assert res.data["cedula"] == DIGITS


def test_patch_cedula_normalized_to_digits_only(auth_client, receptionist_user):
    client = auth_client(receptionist_user)
    created = client.post("/api/patients/", _payload(cedula=DIGITS), format="json")
    assert created.status_code == 201, created.data

    patched = client.patch(
        f"/api/patients/{created.data['id']}/",
        {"cedula": HYPHENATED},
        format="json",
    )
    assert patched.status_code == 200, patched.data
    assert patched.data["cedula"] == DIGITS

    # Follow-up GET also returns digits-only (stored, not just echo).
    res = client.get(f"/api/patients/{created.data['id']}/")
    assert res.status_code == 200
    assert res.data["cedula"] == DIGITS


def test_patch_does_not_touch_cedula_when_absent(auth_client, receptionist_user):
    client = auth_client(receptionist_user)
    created = client.post(
        "/api/patients/", _payload(cedula=DIGITS), format="json"
    )
    assert created.status_code == 201, created.data

    patched = client.patch(
        f"/api/patients/{created.data['id']}/",
        {"phone": "8095557777"},
        format="json",
    )
    assert patched.status_code == 200, patched.data
    assert patched.data["cedula"] == DIGITS


@pytest.mark.parametrize(
    "bad",
    [
        "010-0108492",      # 10 digits
        "010010849201",     # 12 digits
        "abc1234567890",    # 10 digits + letters
        "123",              # 3 digits
    ],
)
def test_cedula_with_wrong_digit_count_rejected(auth_client, receptionist_user, bad):
    res = auth_client(receptionist_user).post(
        "/api/patients/", _payload(cedula=bad), format="json"
    )
    assert res.status_code == 400, res.data
    assert "cedula" in res.data


def test_cedula_with_extra_whitespace_still_accepted(auth_client, receptionist_user):
    res = auth_client(receptionist_user).post(
        "/api/patients/", _payload(cedula=f" {HYPHENATED} "), format="json"
    )
    assert res.status_code == 201, res.data
    assert res.data["cedula"] == DIGITS


def test_empty_cedula_rejected_on_create(auth_client, receptionist_user):
    res = auth_client(receptionist_user).post(
        "/api/patients/", _payload(cedula=""), format="json"
    )
    assert res.status_code == 400, res.data
    assert "cedula" in res.data


def test_empty_cedula_still_allowed_on_update(auth_client, receptionist_user):
    client = auth_client(receptionist_user)
    created = client.post(
        "/api/patients/", _payload(cedula=DIGITS), format="json"
    )
    assert created.status_code == 201, created.data

    patched = client.patch(
        f"/api/patients/{created.data['id']}/",
        {"cedula": ""},
        format="json",
    )
    assert patched.status_code == 200, patched.data
    assert patched.data["cedula"] == ""


def test_cedula_encrypted_at_rest_is_digits_only(auth_client, receptionist_user):
    auth_client(receptionist_user).post(
        "/api/patients/", _payload(cedula=HYPHENATED), format="json"
    )
    with connection.cursor() as cursor:
        cursor.execute("SELECT cedula FROM patients_patient LIMIT 1")
        (raw_cedula,) = cursor.fetchone()
    assert is_encrypted(raw_cedula)
    assert HYPHENATED not in raw_cedula
    # Model layer decrypts to the normalized digits-only value.
    patient = Patient.objects.get()
    assert patient.cedula == DIGITS
