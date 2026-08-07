"""ARS + Patient insurance coverage.

- ARS seeds (SEMMA "SM" / SENASA "SE" + programs) are readable via /api/ars/
  for any authenticated staff user.
- Write permission matrix on /api/ars/: only ADMIN and RECEPTIONIST may
  create/update; other roles get 403; anonymous gets 401.
- Nested writable programs are reconciled on create/update (PATCH removes
  programs not sent).
- Patient insurance: ars + matching ars_program accepted (201, echoes names);
  program from a different ARS rejected (400); cedula stored digits-only and
  must have exactly 11 digits; nss digits-only enforced; all insurance fields
  optional.
- PII masking: ADMIN/DOCTOR/NURSE/RECEPTIONIST see full
  phone/address/email/cedula/nss; IT and CENTER_MANAGER see redacted ("•").
- Audit: ARS create by receptionist logs AuditLog(CREATE, ARS); a real
  login+logout token flow logs LOGIN and LOGOUT.
"""

import pytest

from apps.ars.models import ARS
from apps.core.models import AuditLog
from apps.patients.models import Patient

FULL_PII = {
    "phone": "8095550100",
    "address": "123 Main St, Springfield",
    "email": "jane.doe@example.com",
    "cedula": "010-0108492-0",
    "nss": "123456789",
}


def _patient_payload(**overrides):
    data = {
        "first_name": "Jane",
        "last_name": "Doe",
        "birth_date": "1990-05-12",
        "gender": "FEMALE",
        "phone": FULL_PII["phone"],
        "address": FULL_PII["address"],
        "email": FULL_PII["email"],
        "cedula": FULL_PII["cedula"],
        "nss": FULL_PII["nss"],
    }
    data.update(overrides)
    return data


def _patient_with_pii():
    return Patient.objects.create(
        first_name="Jane",
        last_name="Doe",
        gender="FEMALE",
        **FULL_PII,
    )


# ---------------------------------------------------------------------------
# ARS seeds via API
# ---------------------------------------------------------------------------

def test_seeded_ars_visible_to_staff(auth_client, doctor_user):
    res = auth_client(doctor_user).get("/api/ars/")
    assert res.status_code == 200
    results = res.data["results"]
    by_id = {item["ars_id"]: item for item in results}
    assert "SM" in by_id and "SE" in by_id

    sm = by_id["SM"]
    assert sm["name"] == "SEMMA"
    assert [p["name"] for p in sm["programs"]] == ["P Y P SEMMA"]
    assert all(p["id"] for p in sm["programs"])

    se = by_id["SE"]
    assert se["name"] == "SENASA"
    assert [p["name"] for p in se["programs"]] == ["SENASA Contigo"]
    assert all(p["id"] for p in se["programs"])


# ---------------------------------------------------------------------------
# /api/ars/ write permission matrix
# ---------------------------------------------------------------------------

def test_receptionist_can_create_and_patch_ars(auth_client, receptionist_user):
    client = auth_client(receptionist_user)
    created = client.post("/api/ars/", {"ars_id": "RX", "name": "ARS RX"}, format="json")
    assert created.status_code == 201, created.data
    assert created.data["ars_id"] == "RX"
    patched = client.patch(
        f"/api/ars/{created.data['id']}/", {"name": "ARS RX v2"}, format="json"
    )
    assert patched.status_code == 200, patched.data
    assert patched.data["name"] == "ARS RX v2"


def test_admin_can_create_ars(auth_client, admin_user):
    res = auth_client(admin_user).post(
        "/api/ars/", {"ars_id": "AD", "name": "ARS AD"}, format="json"
    )
    assert res.status_code == 201, res.data


@pytest.mark.parametrize("role_fixture", ["doctor_user", "nurse_user", "it_user"])
def test_non_manager_roles_cannot_create_ars(request, auth_client, role_fixture):
    user = request.getfixturevalue(role_fixture)
    res = auth_client(user).post(
        "/api/ars/", {"ars_id": "NO", "name": "ARS NO"}, format="json"
    )
    assert res.status_code == 403, res.data


def test_anonymous_cannot_create_ars(api_client):
    res = api_client.post(
        "/api/ars/", {"ars_id": "AN", "name": "ARS AN"}, format="json"
    )
    assert res.status_code in (401, 403)


def test_anonymous_cannot_read_ars(api_client):
    assert api_client.get("/api/ars/").status_code in (401, 403)


# ---------------------------------------------------------------------------
# Nested programs handling
# ---------------------------------------------------------------------------

def test_create_ars_with_programs_returns_nested(auth_client, receptionist_user):
    res = auth_client(receptionist_user).post(
        "/api/ars/",
        {"ars_id": "PX", "name": "ARS PX", "programs": [{"name": "X"}]},
        format="json",
    )
    assert res.status_code == 201, res.data
    assert [p["name"] for p in res.data["programs"]] == ["X"]
    assert all("id" in p for p in res.data["programs"])


def test_create_ars_with_zero_programs_allowed(auth_client, receptionist_user):
    res = auth_client(receptionist_user).post(
        "/api/ars/",
        {"ars_id": "Z0", "name": "ARS Z0", "programs": []},
        format="json",
    )
    assert res.status_code == 201, res.data
    assert res.data["programs"] == []
    assert ARS.objects.get(ars_id="Z0").programs.count() == 0


def test_patch_ars_programs_removes_unsent(auth_client, receptionist_user):
    client = auth_client(receptionist_user)
    created = client.post(
        "/api/ars/",
        {"ars_id": "RM", "name": "ARS RM", "programs": [{"name": "A"}, {"name": "B"}]},
        format="json",
    )
    assert created.status_code == 201, created.data
    ars_id = created.data["id"]

    # Replacing the program list with a brand-new program must drop the
    # previously stored programs (A and B) that were not sent.
    patched = client.patch(
        f"/api/ars/{ars_id}/",
        {"programs": [{"name": "C"}]},
        format="json",
    )
    assert patched.status_code == 200, patched.data

    res = client.get(f"/api/ars/{ars_id}/")
    assert res.status_code == 200
    assert [p["name"] for p in res.data["programs"]] == ["C"]


# ---------------------------------------------------------------------------
# Patient insurance binding
# ---------------------------------------------------------------------------

def _seeded_ars(ars_id="SM"):
    return ARS.objects.get(ars_id=ars_id)


def test_patient_with_matching_ars_program(auth_client, receptionist_user):
    ars = _seeded_ars("SM")
    program = ars.programs.get(name="P Y P SEMMA")
    res = auth_client(receptionist_user).post(
        "/api/patients/",
        _patient_payload(ars=ars.id, ars_program=program.id),
        format="json",
    )
    assert res.status_code == 201, res.data
    assert res.data["ars"] == ars.id
    assert res.data["ars_name"] == "SEMMA"
    assert res.data["ars_program"] == program.id
    assert res.data["ars_program_name"] == "P Y P SEMMA"
    assert res.data["cedula"] == "01001084920"
    assert res.data["nss"] == "123456789"


def test_patient_program_from_different_ars_rejected(auth_client, receptionist_user):
    sm = _seeded_ars("SM")
    se_program = _seeded_ars("SE").programs.get(name="SENASA Contigo")
    res = auth_client(receptionist_user).post(
        "/api/patients/",
        _patient_payload(ars=sm.id, ars_program=se_program.id),
        format="json",
    )
    assert res.status_code == 400, res.data
    assert "ars_program" in res.data


def test_invalid_cedula_length_rejected(auth_client, receptionist_user):
    res = auth_client(receptionist_user).post(
        "/api/patients/", _patient_payload(cedula="010-0108492"), format="json"
    )
    assert res.status_code == 400, res.data
    assert "cedula" in res.data

    res = auth_client(receptionist_user).post(
        "/api/patients/", _patient_payload(cedula="010010849201"), format="json"
    )
    assert res.status_code == 400, res.data
    assert "cedula" in res.data


def test_cedula_stored_digits_only(auth_client, receptionist_user):
    res = auth_client(receptionist_user).post(
        "/api/patients/", _patient_payload(cedula="010-0108492-0"), format="json"
    )
    assert res.status_code == 201, res.data
    assert res.data["cedula"] == "01001084920"


def test_non_numeric_nss_rejected(auth_client, receptionist_user):
    res = auth_client(receptionist_user).post(
        "/api/patients/", _patient_payload(nss="abc123"), format="json"
    )
    assert res.status_code == 400, res.data
    assert "nss" in res.data


def test_numeric_nss_accepted(auth_client, receptionist_user):
    res = auth_client(receptionist_user).post(
        "/api/patients/", _patient_payload(nss="123456789"), format="json"
    )
    assert res.status_code == 201, res.data


def test_nss_max_11_digits_enforced(auth_client, receptionist_user):
    res = auth_client(receptionist_user).post(
        "/api/patients/", _patient_payload(nss="123456789012"), format="json"
    )
    assert res.status_code == 400, res.data
    assert "nss" in res.data


def test_nss_fullwidth_digits_normalized(auth_client, receptionist_user):
    res = auth_client(receptionist_user).post(
        "/api/patients/", _patient_payload(nss="１２３４５６７８９０１"), format="json"
    )
    assert res.status_code == 201, res.data
    assert res.data["nss"] == "12345678901"


def test_insurance_fields_all_optional(auth_client, receptionist_user):
    res = auth_client(receptionist_user).post(
        "/api/patients/",
        _patient_payload(cedula="", nss="", ars=None, ars_program=None),
        format="json",
    )
    assert res.status_code == 201, res.data
    assert res.data["ars"] is None
    assert res.data["ars_name"] is None
    assert res.data["ars_program"] is None
    assert res.data["ars_program_name"] is None
    assert res.data["cedula"] == ""
    assert res.data["nss"] == ""


# ---------------------------------------------------------------------------
# PII masking by role (incl. cedula/nss)
# ---------------------------------------------------------------------------

def test_receptionist_sees_full_pii(auth_client, receptionist_user):
    patient = _patient_with_pii()
    res = auth_client(receptionist_user).get(f"/api/patients/{patient.id}/")
    assert res.status_code == 200
    for field, value in FULL_PII.items():
        assert res.data[field] == value, f"{field} should be full for receptionist"


@pytest.mark.parametrize("role_fixture", ["admin_user", "doctor_user", "nurse_user"])
def test_admin_doctor_nurse_see_full_pii(request, auth_client, role_fixture):
    user = request.getfixturevalue(role_fixture)
    patient = _patient_with_pii()
    res = auth_client(user).get(f"/api/patients/{patient.id}/")
    assert res.status_code == 200
    for field, value in FULL_PII.items():
        assert res.data[field] == value, f"{field} should be full for {role_fixture}"


@pytest.mark.parametrize("role_fixture", ["it_user", "cm_user"])
def test_it_and_cm_see_redacted_pii(request, auth_client, make_user, role_fixture):
    if role_fixture == "cm_user":
        user = make_user("cm", "CENTER_MANAGER")
    else:
        user = request.getfixturevalue(role_fixture)
    patient = _patient_with_pii()
    res = auth_client(user).get(f"/api/patients/{patient.id}/")
    assert res.status_code == 200
    for field in ("phone", "address", "email", "cedula", "nss"):
        assert "•" in res.data[field], f"{field} should be redacted for {role_fixture}"
        assert res.data[field] != FULL_PII[field]


# ---------------------------------------------------------------------------
# Audit trail
# ---------------------------------------------------------------------------

def test_audit_log_on_ars_create_by_receptionist(auth_client, receptionist_user):
    res = auth_client(receptionist_user).post(
        "/api/ars/", {"ars_id": "AU", "name": "ARS AU"}, format="json"
    )
    assert res.status_code == 201, res.data
    assert AuditLog.objects.filter(
        action="CREATE", target_type="ARS", user=receptionist_user
    ).exists()


def test_audit_logs_login_and_logout(api_client, make_user):
    user = make_user("audit_usr", "RECEPTIONIST")
    login = api_client.post(
        "/api/auth/login/",
        {"username": user.username, "password": "pass12345"},
        format="json",
    )
    assert login.status_code == 200, login.data
    assert AuditLog.objects.filter(user=user, action="LOGIN").exists()

    logout = api_client.post(
        "/api/auth/logout/",
        {},
        HTTP_AUTHORIZATION=f"Bearer {login.data['access']}",
        format="json",
    )
    assert logout.status_code == 204
    assert AuditLog.objects.filter(user=user, action="LOGOUT").exists()
