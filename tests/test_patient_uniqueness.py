"""Cedula is required and must match exactly one active patient; NSS is
optional but, when present, must also match exactly one active patient.

Cedula/NSS are encrypted at rest (non-deterministic ciphertext), so
uniqueness is enforced via the deterministic cedula_hash/nss_hash blind-index
columns -- both at the API layer (PatientSerializer, for a friendly 400) and
as a DB-level partial UniqueConstraint scoped to active=True (Patient.Meta),
which is the backstop if the serializer layer is ever bypassed.
"""

import pytest
from django.db import IntegrityError, transaction

from apps.patients.models import Patient


def _payload(**overrides):
    data = {
        "first_name": "Uniq",
        "last_name": "Test",
        "gender": "FEMALE",
        "birth_date": "1990-05-12",
        "cedula": "20100000001",
    }
    data.update(overrides)
    return data


def test_cedula_required_on_create(auth_client, receptionist_user):
    res = auth_client(receptionist_user).post(
        "/api/patients/", _payload(cedula=""), format="json"
    )
    assert res.status_code == 400, res.data
    assert "cedula" in res.data


def test_duplicate_cedula_rejected_on_create(auth_client, receptionist_user):
    client = auth_client(receptionist_user)
    first = client.post("/api/patients/", _payload(cedula="20100000010"), format="json")
    assert first.status_code == 201, first.data

    dup = client.post(
        "/api/patients/",
        _payload(first_name="Other", cedula="20100000010"),
        format="json",
    )
    assert dup.status_code == 400, dup.data
    assert "cedula" in dup.data
    assert "already exists" in str(dup.data["cedula"])


def test_duplicate_cedula_rejected_on_update(auth_client, receptionist_user):
    client = auth_client(receptionist_user)
    a = client.post("/api/patients/", _payload(cedula="20100000020"), format="json")
    b = client.post(
        "/api/patients/", _payload(first_name="Other", cedula="20100000021"), format="json"
    )
    assert a.status_code == 201 and b.status_code == 201

    res = client.patch(
        f"/api/patients/{b.data['id']}/", {"cedula": "20100000020"}, format="json"
    )
    assert res.status_code == 400, res.data
    assert "cedula" in res.data


def test_duplicate_nss_rejected_on_create(auth_client, receptionist_user):
    client = auth_client(receptionist_user)
    first = client.post(
        "/api/patients/",
        _payload(cedula="20100000030", nss="30100000001"),
        format="json",
    )
    assert first.status_code == 201, first.data

    dup = client.post(
        "/api/patients/",
        _payload(first_name="Other", cedula="20100000031", nss="30100000001"),
        format="json",
    )
    assert dup.status_code == 400, dup.data
    assert "nss" in dup.data
    assert "already exists" in str(dup.data["nss"])


def test_duplicate_nss_rejected_on_update(auth_client, receptionist_user):
    client = auth_client(receptionist_user)
    a = client.post(
        "/api/patients/",
        _payload(cedula="20100000040", nss="30100000002"),
        format="json",
    )
    b = client.post(
        "/api/patients/", _payload(first_name="Other", cedula="20100000041"), format="json"
    )
    assert a.status_code == 201 and b.status_code == 201

    res = client.patch(
        f"/api/patients/{b.data['id']}/", {"nss": "30100000002"}, format="json"
    )
    assert res.status_code == 400, res.data
    assert "nss" in res.data


def test_blank_nss_allowed_for_multiple_patients(auth_client, receptionist_user):
    client = auth_client(receptionist_user)
    a = client.post(
        "/api/patients/", _payload(first_name="A", cedula="20100000050"), format="json"
    )
    b = client.post(
        "/api/patients/", _payload(first_name="B", cedula="20100000051"), format="json"
    )
    assert a.status_code == 201, a.data
    assert b.status_code == 201, b.data
    assert a.data["nss"] == "" and b.data["nss"] == ""


def test_soft_deleted_patient_frees_cedula_and_nss_for_reuse(
    auth_client, admin_user
):
    client = auth_client(admin_user)
    original = client.post(
        "/api/patients/",
        _payload(cedula="20100000060", nss="30100000003"),
        format="json",
    )
    assert original.status_code == 201, original.data

    deleted = client.delete(f"/api/patients/{original.data['id']}/")
    assert deleted.status_code == 204

    reused = client.post(
        "/api/patients/",
        _payload(first_name="New", cedula="20100000060", nss="30100000003"),
        format="json",
    )
    assert reused.status_code == 201, reused.data


def test_db_constraint_backstops_duplicate_cedula_bypassing_serializer(db):
    Patient.objects.create(
        first_name="A", last_name="X", cedula="20100000070"
    )
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            Patient.objects.create(first_name="B", last_name="Y", cedula="20100000070")


def test_db_constraint_backstops_duplicate_nss_bypassing_serializer(db):
    Patient.objects.create(
        first_name="A", last_name="X", cedula="20100000080", nss="30100000004"
    )
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            Patient.objects.create(
                first_name="B", last_name="Y", cedula="20100000081", nss="30100000004"
            )


def test_db_constraint_allows_multiple_blank_nss_at_model_level(db):
    Patient.objects.create(first_name="A", last_name="X", cedula="20100000090")
    Patient.objects.create(first_name="B", last_name="Y", cedula="20100000091")
