"""Follow-up fixes from the QA agent and security audit.

- F1: patient names / staff names / CM appointment notes masked for IT & CM
      on medical records, consultation logs, and appointments.
- F2: demoting an ADMIN clears is_staff / is_superuser.
- QA BUG-1/BUG-2: patient email and birth_date are validated.
- F3: validate_phone normalizes NFKC (fullwidth) digits and rejects letters.
- F4: IT / CM cannot use ?search= (search_name) as a PII-existence oracle.
"""

from apps.appointments.models import Appointment
from apps.doctors.models import DoctorProfile
from apps.patients.models import Patient
from apps.records.models import ConsultationLog, MedicalRecord

MASK = "•"


def _make_patient(**overrides):
    data = {
        "first_name": "Jane",
        "last_name": "Doe",
        "gender": "FEMALE",
        "phone": "8095550100",
    }
    data.update(overrides)
    return Patient.objects.create(**data)


def _make_doctor(user):
    return DoctorProfile.objects.create(
        user=user,
        specialty="Cardiology",
        license_number=f"LIC-{user.id}",
        contact_phone="8095550000",
    )


def _make_record(patient, doctor_user, **overrides):
    data = {
        "title": "Follow-up",
        "diagnosis": "Hypertension",
        "notes": "Monitor weekly",
    }
    data.update(overrides)
    return MedicalRecord.objects.create(
        patient=patient,
        created_by=doctor_user,
        **data,
    )


# ---------------------------------------------------------------------------
# F1: masking on records / logs / appointments for masked roles
# ---------------------------------------------------------------------------

def test_it_and_cm_see_masked_patient_name_on_record(auth_client, make_user, doctor_user):
    patient = _make_patient()
    record = _make_record(patient, doctor_user)
    for user in (make_user("it", "IT"), make_user("cm", "CENTER_MANAGER")):
        res = auth_client(user).get(f"/api/medical-records/{record.id}/")
        assert res.status_code == 200
        assert res.data["patient_info"]["full_name"] != "Jane Doe"
        assert MASK in res.data["patient_info"]["full_name"]
        assert res.data["created_by_name"] != doctor_user.username
        assert MASK in res.data["created_by_name"]


def test_receptionist_sees_full_patient_name_on_record(auth_client, receptionist_user, doctor_user):
    patient = _make_patient()
    record = _make_record(patient, doctor_user)
    res = auth_client(receptionist_user).get(f"/api/medical-records/{record.id}/")
    assert res.status_code == 200
    assert res.data["patient_info"]["full_name"] == "Jane Doe"


def test_it_and_cm_see_masked_patient_name_on_log(auth_client, make_user, doctor_user):
    patient = _make_patient()
    log = ConsultationLog.objects.create(
        patient=patient,
        doctor=doctor_user,
        subjective="Headaches",
        plan="MRI",
    )
    for user in (make_user("it", "IT"), make_user("cm", "CENTER_MANAGER")):
        res = auth_client(user).get(f"/api/consultation-logs/{log.id}/")
        assert res.status_code == 200
        assert res.data["patient_info"]["full_name"] != "Jane Doe"
        assert MASK in res.data["patient_info"]["full_name"]
        assert res.data["doctor_name"] != doctor_user.username
        assert MASK in res.data["doctor_name"]


def test_it_and_cm_see_masked_patient_name_and_notes_on_appointment(
    auth_client, make_user, receptionist_user, doctor_user
):
    patient = _make_patient()
    profile = _make_doctor(doctor_user)
    appt = Appointment.objects.create(
        patient=patient,
        doctor=profile,
        date_time="2026-09-01T10:00:00Z",
        notes="sensitive appointment note",
        created_by=receptionist_user,
    )
    for user in (make_user("it", "IT"), make_user("cm", "CENTER_MANAGER")):
        res = auth_client(user).get(f"/api/appointments/{appt.id}/")
        assert res.status_code == 200
        assert res.data["patient_info"]["full_name"] != "Jane Doe"
        assert MASK in res.data["patient_info"]["full_name"]
        assert res.data["notes"] != "sensitive appointment note"
        assert MASK in res.data["notes"]


# ---------------------------------------------------------------------------
# F2: admin demotion clears staff / superuser
# ---------------------------------------------------------------------------

def test_demoted_admin_loses_staff_and_superuser(auth_client, admin_user, make_user):
    victim = make_user("victim_admin", "ADMIN")
    assert victim.is_staff is True and victim.is_superuser is True

    res = auth_client(admin_user).patch(
        f"/api/auth/users/{victim.id}/", {"role": "DOCTOR"}, format="json"
    )
    assert res.status_code == 200, res.data
    victim.refresh_from_db()
    assert victim.role == "DOCTOR"
    assert victim.is_staff is False
    assert victim.is_superuser is False


def test_admin_still_keeps_staff_after_save(make_user):
    admin = make_user("still_admin", "ADMIN")
    admin.refresh_from_db()
    assert admin.is_staff is True
    assert admin.is_superuser is True


# ---------------------------------------------------------------------------
# QA BUG-1 / BUG-2: patient email and birth_date validation
# ---------------------------------------------------------------------------

def _patient_payload(**overrides):
    data = {
        "first_name": "Mail",
        "last_name": "Test",
        "gender": "FEMALE",
        "phone": "8095550100",
        "email": "valid@example.com",
        "birth_date": "1990-05-12",
        "cedula": "01098765434",
    }
    data.update(overrides)
    return data


def test_patient_email_must_be_valid(auth_client, receptionist_user):
    res = auth_client(receptionist_user).post(
        "/api/patients/", _patient_payload(email="not-an-email"), format="json"
    )
    assert res.status_code == 400, res.data
    assert "email" in res.data


def test_patient_email_optional(auth_client, receptionist_user):
    res = auth_client(receptionist_user).post(
        "/api/patients/", _patient_payload(email=""), format="json"
    )
    assert res.status_code == 201, res.data
    assert res.data["email"] == ""


def test_patient_birth_date_must_be_iso_date(auth_client, receptionist_user):
    res = auth_client(receptionist_user).post(
        "/api/patients/", _patient_payload(birth_date="not-a-date"), format="json"
    )
    assert res.status_code == 400, res.data
    assert "birth_date" in res.data


def test_patient_birth_date_cannot_be_future(auth_client, receptionist_user):
    res = auth_client(receptionist_user).post(
        "/api/patients/", _patient_payload(birth_date="2999-01-01"), format="json"
    )
    assert res.status_code == 400, res.data
    assert "birth_date" in res.data


def test_patient_birth_date_required(auth_client, receptionist_user):
    # Birth date is mandatory (business rule tightened after this test was
    # first written, when it was optional).
    res = auth_client(receptionist_user).post(
        "/api/patients/", _patient_payload(birth_date=""), format="json"
    )
    assert res.status_code == 400, res.data
    assert "birth_date" in res.data


# ---------------------------------------------------------------------------
# F3: validate_phone unicode normalization (fullwidth digits)
# ---------------------------------------------------------------------------

def test_fullwidth_digits_normalized_to_ascii(auth_client, receptionist_user):
    res = auth_client(receptionist_user).post(
        "/api/patients/", _patient_payload(phone="（８０９）５５５－１２１２"), format="json"
    )
    assert res.status_code == 201, res.data
    assert res.data["phone"] == "8095551212"


def test_unicode_letter_rejected(auth_client, receptionist_user):
    res = auth_client(receptionist_user).post(
        "/api/patients/", _patient_payload(phone="éêâ8095551212"), format="json"
    )
    assert res.status_code == 400, res.data
    assert "phone" in res.data


def test_arabic_indic_digits_rejected(auth_client, receptionist_user):
    # U+0660..U+0669 are not ASCII \d; after NFKC they remain non-ASCII and are
    # dropped, leaving 0 digits -> invalid length -> 400.
    res = auth_client(receptionist_user).post(
        "/api/patients/", _patient_payload(phone="٨٠٩٥٥٥١٢١٢"), format="json"
    )
    assert res.status_code == 400, res.data
    assert "phone" in res.data


# ---------------------------------------------------------------------------
# F4: search_name oracle closed for masked roles
# ---------------------------------------------------------------------------

def test_receptionist_can_search_by_name(auth_client, receptionist_user):
    _make_patient(first_name="Jane", last_name="Smith")
    _make_patient(first_name="Peter", last_name="Jones")
    res = auth_client(receptionist_user).get("/api/patients/?search=jane")
    assert res.status_code == 200
    assert res.data["count"] == 1
    res = auth_client(receptionist_user).get("/api/patients/?search_name=jane%20smith")
    assert res.status_code == 200
    assert res.data["count"] == 1


def test_it_and_cm_cannot_search_by_name(auth_client, make_user):
    _make_patient(first_name="Jane", last_name="Smith")
    _make_patient(first_name="Peter", last_name="Jones")
    for user in (make_user("it", "IT"), make_user("cm", "CENTER_MANAGER")):
        res = auth_client(user).get("/api/patients/?search=jane")
        assert res.status_code == 200
        assert res.data["count"] == 2, "search must be ignored for masked roles"
        res = auth_client(user).get("/api/patients/?search_name=janesmith")
        assert res.status_code == 200
        assert res.data["count"] == 2, "search_name filter must be ignored for masked roles"
