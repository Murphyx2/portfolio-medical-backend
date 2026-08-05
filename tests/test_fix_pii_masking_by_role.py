"""Fix P2 / H-04: GET /api/patients/{id}/ PII masking by role.

IT, RECEPTIONIST and CENTER_MANAGER must see masked phone/address/email
(e.g. "+1••••99", "jo••••om"). DOCTOR, NURSE and ADMIN must see full values.
"""

from apps.patients.models import Patient

MASK = "••••"
FULL = {
    "phone": "+1-555-0100",
    "address": "123 Main St, Springfield",
    "email": "jane.doe@example.com",
}


def _make_patient(**overrides):
    data = {
        "first_name": "Jane",
        "last_name": "Doe",
        "gender": "FEMALE",
        "phone": FULL["phone"],
        "address": FULL["address"],
        "email": FULL["email"],
    }
    data.update(overrides)
    return Patient.objects.create(**data)


def _masked(patient_id, auth_client, user):
    res = auth_client(user).get(f"/api/patients/{patient_id}/")
    assert res.status_code == 200, res.data
    data = res.data
    assert data["phone"] != FULL["phone"] and MASK in data["phone"]
    assert data["email"] != FULL["email"] and MASK in data["email"]
    assert data["address"] != FULL["address"] and MASK in data["address"]
    return data


def _full(patient_id, auth_client, user):
    res = auth_client(user).get(f"/api/patients/{patient_id}/")
    assert res.status_code == 200, res.data
    data = res.data
    assert data["phone"] == FULL["phone"]
    assert data["email"] == FULL["email"]
    assert data["address"] == FULL["address"]
    return data


def test_it_sees_masked_pii(auth_client, it_user, receptionist_user):
    patient = _make_patient()
    data = _masked(patient.id, auth_client, it_user)
    # exact masking shape: "xx••••yy"
    assert data["phone"].startswith("+1") and data["phone"].endswith("00")
    assert data["email"].startswith("ja") and data["email"].endswith("om")
    assert data["address"].startswith("12") and data["address"].endswith("ld")


def test_receptionist_sees_masked_pii(auth_client, receptionist_user):
    patient = _make_patient()
    _masked(patient.id, auth_client, receptionist_user)


def test_center_manager_sees_masked_pii(auth_client, receptionist_user, make_user):
    cm_user = make_user("cm", "CENTER_MANAGER")
    patient = _make_patient()
    _masked(patient.id, auth_client, cm_user)


def test_doctor_sees_full_pii(auth_client, doctor_user):
    patient = _make_patient()
    _full(patient.id, auth_client, doctor_user)


def test_nurse_sees_full_pii(auth_client, nurse_user):
    patient = _make_patient()
    _full(patient.id, auth_client, nurse_user)


def test_admin_sees_full_pii(auth_client, admin_user):
    patient = _make_patient()
    _full(patient.id, auth_client, admin_user)
