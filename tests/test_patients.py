from django.db import connection

from apps.core.encryption import is_encrypted
from apps.patients.models import Patient


def _patient_payload(**overrides):
    data = {
        "first_name": "Jane",
        "last_name": "Doe",
        "birth_date": "1990-05-12",
        "gender": "FEMALE",
        "phone": "8095550100",
        "address": "123 Main St, Springfield",
        "email": "jane.doe@example.com",
    }
    data.update(overrides)
    return data


def test_create_patient_by_receptionist(auth_client, receptionist_user):
    res = auth_client(receptionist_user).post(
        "/api/patients/", _patient_payload(), format="json"
    )
    assert res.status_code == 201
    patient = Patient.objects.get(pk=res.data["id"])
    assert patient.phone == "8095550100"


def test_patient_pii_is_encrypted_at_rest(auth_client, receptionist_user):
    auth_client(receptionist_user).post("/api/patients/", _patient_payload(), format="json")
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT phone, address, email, first_name, last_name, birth_date "
            "FROM patients_patient LIMIT 1"
        )
        raw_phone, raw_address, raw_email, raw_fn, raw_ln, raw_bd = cursor.fetchone()
    assert is_encrypted(raw_phone)
    assert is_encrypted(raw_address)
    assert is_encrypted(raw_email)
    assert is_encrypted(raw_fn)
    assert is_encrypted(raw_ln)
    assert is_encrypted(raw_bd)
    assert "8095550100" not in raw_phone
    assert "Jane" not in raw_fn


def test_anonymous_cannot_read_patients(api_client):
    assert api_client.get("/api/patients/").status_code == 401


def test_doctor_can_read_full_pii(auth_client, doctor_user, receptionist_user):
    auth_client(receptionist_user).post("/api/patients/", _patient_payload(), format="json")
    res = auth_client(doctor_user).get("/api/patients/")
    assert res.status_code == 200
    result = res.data["results"][0]
    assert result["phone"] == "8095550100"
    assert result["email"] == "jane.doe@example.com"


def test_it_sees_redacted_pii(auth_client, it_user, receptionist_user):
    auth_client(receptionist_user).post("/api/patients/", _patient_payload(), format="json")
    res = auth_client(it_user).get("/api/patients/")
    assert res.status_code == 200
    result = res.data["results"][0]
    assert result["phone"] != "8095550100"
    assert "555" not in result["phone"]


def test_nurse_cannot_modify_patients(auth_client, nurse_user, receptionist_user):
    auth_client(receptionist_user).post("/api/patients/", _patient_payload(), format="json")
    client = auth_client(nurse_user)
    res = client.post("/api/patients/", _patient_payload(), format="json")
    assert res.status_code in (401, 403)


def test_update_patient_keeps_encryption(auth_client, receptionist_user):
    created = auth_client(receptionist_user).post(
        "/api/patients/", _patient_payload(), format="json"
    )
    pid = created.data["id"]
    res = auth_client(receptionist_user).patch(
        f"/api/patients/{pid}/",
        {"phone": "8095550999"},
        format="json",
    )
    assert res.status_code == 200
    assert Patient.objects.get(pk=pid).phone == "8095550999"
