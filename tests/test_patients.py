from django.db import connection
from django.test.utils import CaptureQueriesContext

from apps.ars.models import ARS, ARSProgram
from apps.centers.models import DoctorCenterBinding, MedicalCenter
from apps.core.encryption import is_encrypted
from apps.core.models import AuditLog
from apps.doctors.models import DoctorProfile
from apps.patients.models import Patient
from apps.records.models import MedicalRecord


def _patient_payload(**overrides):
    data = {
        "first_name": "Jane",
        "last_name": "Doe",
        "birth_date": "1990-05-12",
        "gender": "FEMALE",
        "phone": "8095550100",
        "address": "123 Main St, Springfield",
        "email": "jane.doe@example.com",
        "cedula": "01098765432",
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


def test_create_patient_with_extra_phones(auth_client, receptionist_user):
    res = auth_client(receptionist_user).post(
        "/api/patients/",
        _patient_payload(extra_phones=[{"phone": "8095550200"}, {"phone": "8095550300"}]),
        format="json",
    )
    assert res.status_code == 201, res.data
    patient = Patient.objects.get(pk=res.data["id"])
    assert sorted(p.phone for p in patient.extra_phones.all()) == ["8095550200", "8095550300"]
    assert sorted(p["phone"] for p in res.data["extra_phones"]) == ["8095550200", "8095550300"]


def test_update_patient_replaces_extra_phones(auth_client, receptionist_user):
    create = auth_client(receptionist_user).post(
        "/api/patients/",
        _patient_payload(extra_phones=[{"phone": "8095550200"}]),
        format="json",
    )
    patient_id = create.data["id"]

    res = auth_client(receptionist_user).patch(
        f"/api/patients/{patient_id}/",
        {"extra_phones": [{"phone": "8095550400"}]},
        format="json",
    )
    assert res.status_code == 200, res.data
    patient = Patient.objects.get(pk=patient_id)
    assert [p.phone for p in patient.extra_phones.all()] == ["8095550400"]


def test_extra_phones_encrypted_at_rest(auth_client, receptionist_user):
    res = auth_client(receptionist_user).post(
        "/api/patients/",
        _patient_payload(extra_phones=[{"phone": "8095550200"}]),
        format="json",
    )
    with connection.cursor() as cursor:
        cursor.execute("SELECT phone FROM patients_patientphonenumber LIMIT 1")
        (raw_phone,) = cursor.fetchone()
    assert is_encrypted(raw_phone)
    assert "8095550200" not in raw_phone


def test_extra_phones_masked_for_it_role(auth_client, receptionist_user, it_user):
    auth_client(receptionist_user).post(
        "/api/patients/",
        _patient_payload(extra_phones=[{"phone": "8095550200"}]),
        format="json",
    )
    res = auth_client(it_user).get("/api/patients/")
    row = res.data["results"][0]
    assert row["extra_phones"][0]["phone"] != "8095550200"


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


# ---------------------------------------------------------------------------
# gender/birth_date: mandatory, only MALE/FEMALE
# ---------------------------------------------------------------------------


def test_birth_date_required_on_create(auth_client, receptionist_user):
    res = auth_client(receptionist_user).post(
        "/api/patients/", _patient_payload(birth_date=""), format="json"
    )
    assert res.status_code == 400, res.data
    assert "birth_date" in res.data


def test_birth_date_omitted_rejected_on_create(auth_client, receptionist_user):
    payload = _patient_payload()
    del payload["birth_date"]
    res = auth_client(receptionist_user).post("/api/patients/", payload, format="json")
    assert res.status_code == 400, res.data
    assert "birth_date" in res.data


def test_birth_date_blanked_rejected_on_update(auth_client, receptionist_user):
    created = auth_client(receptionist_user).post(
        "/api/patients/", _patient_payload(), format="json"
    )
    assert created.status_code == 201, created.data
    res = auth_client(receptionist_user).patch(
        f"/api/patients/{created.data['id']}/", {"birth_date": ""}, format="json"
    )
    assert res.status_code == 400, res.data
    assert "birth_date" in res.data


def test_gender_required_on_create(auth_client, receptionist_user):
    payload = _patient_payload()
    del payload["gender"]
    res = auth_client(receptionist_user).post("/api/patients/", payload, format="json")
    assert res.status_code == 400, res.data
    assert "gender" in res.data


def test_gender_other_no_longer_a_valid_choice(auth_client, receptionist_user):
    res = auth_client(receptionist_user).post(
        "/api/patients/", _patient_payload(gender="OTHER"), format="json"
    )
    assert res.status_code == 400, res.data
    assert "gender" in res.data


def test_gender_male_and_female_still_accepted(auth_client, receptionist_user):
    cedulas = {"MALE": "40100000001", "FEMALE": "40100000002"}
    for gender, cedula in cedulas.items():
        res = auth_client(receptionist_user).post(
            "/api/patients/",
            _patient_payload(cedula=cedula, gender=gender),
            format="json",
        )
        assert res.status_code == 201, res.data
        assert res.data["gender"] == gender


# ---------------------------------------------------------------------------
# query-count regressions (select_related + Exists doctor-scoping)
# ---------------------------------------------------------------------------


def _query_count(client, url):
    with CaptureQueriesContext(connection) as ctx:
        res = client.get(url)
    assert res.status_code == 200
    return len(ctx.captured_queries), res


def test_patient_list_query_count_does_not_scale_with_row_count(
    auth_client, admin_user, db
):
    # ars_name/ars_program_name/center_name are serializer fields sourced
    # from related objects (PatientSerializer); without select_related each
    # row would cost 3 extra queries (N+1).
    ars = ARS.objects.create(ars_id="Q1", name="Insurer")
    program = ARSProgram.objects.create(ars=ars, name="Plan A")
    center = MedicalCenter.objects.create(
        name="Central", code="C1", address="Addr", phone="8095550000"
    )

    def _make(n):
        for i in range(n):
            Patient.objects.create(
                first_name=f"P{i}",
                last_name="X",
                ars=ars,
                ars_program=program,
                center=center,
            )

    client = auth_client(admin_user)
    # Prime the SystemSettings cache (apps/systemsettings/services.py) outside
    # the measured block -- SettingsAnonRateThrottle/SettingsUserRateThrottle
    # (apps/core/throttling.py) read it on every request, and the first read
    # after the autouse clear_cache fixture is a cache miss (one extra DB
    # query) that would otherwise skew this row-count-independent comparison.
    from apps.systemsettings.services import get_settings

    get_settings()
    _make(1)
    n1, _ = _query_count(client, "/api/patients/?page_size=20")
    _make(4)  # 5 patients total
    n5, _ = _query_count(client, "/api/patients/?page_size=20")
    assert n1 == n5


def test_doctor_patient_list_no_duplicate_rows_across_multiple_records(
    auth_client, doctor_user, db
):
    # PatientViewSet doesn't join medical_records at all, so multiple
    # MedicalRecords for the same patient can't produce duplicate rows here.
    center = MedicalCenter.objects.create(
        name="Central", code="C1", address="Addr", phone="8095550000"
    )
    profile = DoctorProfile.objects.create(
        user=doctor_user, license_number="L1", contact_phone="8095550001"
    )
    DoctorCenterBinding.objects.create(
        doctor=profile, center=center, approved=True, approved_by=doctor_user
    )
    patient = Patient.objects.create(first_name="Ana", last_name="Perez", center=center)
    for i in range(3):
        MedicalRecord.objects.create(
            patient=patient, created_by=doctor_user, center=center, title=f"Visit {i}"
        )

    res = auth_client(doctor_user).get("/api/patients/?page_size=20")
    assert res.status_code == 200
    assert res.data["count"] == 1
    ids = [r["id"] for r in res.data["results"]]
    assert ids.count(patient.id) == 1


def test_allergies_and_critical_conditions_encrypted_at_rest(auth_client, receptionist_user):
    res = auth_client(receptionist_user).post(
        "/api/patients/",
        _patient_payload(allergies="Penicillin", critical_conditions="Diabetes"),
        format="json",
    )
    assert res.status_code == 201, res.data
    assert res.data["allergies"] == "Penicillin"
    assert res.data["critical_conditions"] == "Diabetes"
    with connection.cursor() as cursor:
        cursor.execute("SELECT allergies, critical_conditions FROM patients_patient LIMIT 1")
        raw_allergies, raw_conditions = cursor.fetchone()
    assert is_encrypted(raw_allergies)
    assert is_encrypted(raw_conditions)


def test_allergies_masked_for_it_role(auth_client, receptionist_user, it_user):
    create = auth_client(receptionist_user).post(
        "/api/patients/", _patient_payload(allergies="Penicillin"), format="json"
    )
    res = auth_client(it_user).get(f"/api/patients/{create.data['id']}/")
    assert res.data["allergies"] != "Penicillin"


def test_creating_patient_auto_creates_placeholder_record(auth_client, receptionist_user):
    res = auth_client(receptionist_user).post(
        "/api/patients/", _patient_payload(allergies="Penicillin"), format="json"
    )
    assert res.status_code == 201, res.data
    record = MedicalRecord.objects.get(patient_id=res.data["id"])
    assert record.created_by == receptionist_user
    assert record.title == "Registro inicial"
    assert "Penicillin" in record.notes
    assert record.diagnosis == ""


def test_creating_patient_audits_placeholder_record_creation(auth_client, receptionist_user):
    """B7 regression guard: create_initial_record (apps/records/services.py)
    now goes through log_audit -- previously this was a raw MedicalRecord
    .create() call inside PatientViewSet.perform_create with no
    corresponding AuditLog row."""
    res = auth_client(receptionist_user).post(
        "/api/patients/", _patient_payload(), format="json"
    )
    assert res.status_code == 201, res.data
    record = MedicalRecord.objects.get(patient_id=res.data["id"])
    assert AuditLog.objects.filter(
        target_type="MedicalRecord", target_id=record.id, action="CREATE"
    ).exists()
