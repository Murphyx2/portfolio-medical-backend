"""Phone validation: digits-only storage, 10-digit rule, letters rejected.

Spec:
- Stored value is always digits-only (10 digits for DR numbers).
- Formatted input like "(809) 555-1212" is accepted and normalized to digits.
- Letters and invalid lengths (9 or 11 digits) are rejected with 400.
- Patient phone stays optional (empty allowed); center/doctor phone required.
- IT/CENTER_MANAGER masking still applies to the stored digits.
"""

import pytest

from apps.doctors.models import DoctorProfile
from apps.patients.models import Patient

MASK = "•"


def _patient_payload(**overrides):
    data = {
        "first_name": "Phone",
        "last_name": "Test",
        "gender": "FEMALE",
        "phone": "(809) 555-1212",
        "cedula": "01098765433",
    }
    data.update(overrides)
    return data


def _center_payload(**overrides):
    data = {
        "name": "Phone Center",
        "code": "PC001",
        "address": "1 Main St",
        "phone": "(809) 555-1212",
    }
    data.update(overrides)
    return data


def _doctor_payload(user_id, **overrides):
    data = {
        "user": user_id,
        "specialty": "Cardiology",
        "license_number": "LIC-PH",
        "contact_phone": "(809) 555-1212",
    }
    data.update(overrides)
    return data


def test_formatted_phone_stored_digits_only(auth_client, receptionist_user):
    res = auth_client(receptionist_user).post(
        "/api/patients/", _patient_payload(), format="json"
    )
    assert res.status_code == 201, res.data
    patient = Patient.objects.get(pk=res.data["id"])
    assert patient.phone == "8095551212"
    assert res.data["phone"] == "8095551212"


@pytest.mark.parametrize(
    "bad",
    [
        "809-555-121",          # 9 digits
        "80955512123",          # 11 digits
        "abc80955512",          # letters
        "(809) 555-12AB",       # letters mixed in
    ],
)
def test_invalid_patient_phone_rejected(auth_client, receptionist_user, bad):
    res = auth_client(receptionist_user).post(
        "/api/patients/", _patient_payload(phone=bad), format="json"
    )
    assert res.status_code == 400, res.data
    assert "phone" in res.data


def test_empty_patient_phone_still_allowed(auth_client, receptionist_user):
    res = auth_client(receptionist_user).post(
        "/api/patients/", _patient_payload(phone=""), format="json"
    )
    assert res.status_code == 201, res.data
    assert res.data["phone"] == ""


def test_patch_phone_normalized_to_digits_only(auth_client, receptionist_user):
    client = auth_client(receptionist_user)
    created = client.post("/api/patients/", _patient_payload(), format="json")
    assert created.status_code == 201
    pid = created.data["id"]
    patched = client.patch(
        f"/api/patients/{pid}/", {"phone": "829 555 0199"}, format="json"
    )
    assert patched.status_code == 200, patched.data
    assert patched.data["phone"] == "8295550199"


def test_center_phone_validated(auth_client, admin_user):
    client = auth_client(admin_user)
    ok = client.post("/api/centers/", _center_payload(), format="json")
    assert ok.status_code == 201, ok.data
    assert ok.data["phone"] == "8095551212"

    bad = client.post(
        "/api/centers/", _center_payload(phone="809-555-121"), format="json"
    )
    assert bad.status_code == 400, bad.data
    assert "phone" in bad.data


def test_doctor_contact_phone_validated(auth_client, admin_user, doctor_user):
    client = auth_client(admin_user)
    ok = client.post(
        "/api/doctors/profiles/", _doctor_payload(doctor_user.id), format="json"
    )
    assert ok.status_code == 201, ok.data
    assert DoctorProfile.objects.get(pk=ok.data["id"]).contact_phone == "8095551212"

    bad = client.post(
        "/api/doctors/profiles/",
        _doctor_payload(doctor_user.id, contact_phone="llamame!"),
        format="json",
    )
    assert bad.status_code == 400, bad.data
    assert "contact_phone" in bad.data


def test_it_and_cm_still_see_masked_phone(auth_client, it_user, make_user, receptionist_user):
    created = auth_client(receptionist_user).post(
        "/api/patients/", _patient_payload(), format="json"
    )
    pid = created.data["id"]
    for user in (it_user, make_user("cm", "CENTER_MANAGER")):
        res = auth_client(user).get(f"/api/patients/{pid}/")
        assert res.status_code == 200
        assert MASK in res.data["phone"]
        assert res.data["phone"] != "8095551212"
