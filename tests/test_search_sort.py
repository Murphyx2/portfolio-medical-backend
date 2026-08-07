"""Search (`?search=`) and ordering (`?ordering=`) on the list endpoints.

Patients store cedula/NSS/name PII encrypted at rest; name search uses the
plaintext `search_name` index and cedula/NSS search decrypts in Python
(`PatientSearchFilter`). Records reuse the same trick (`RecordSearchFilter`) so
an expediente can be found by its patient's cedula/NSS when names collide.

Security invariants:
- Masked roles (IT/CENTER_MANAGER) cannot search patients by name/cedula/NSS
  (that would be a PII existence oracle) and can search records by title only.
- Unknown `?ordering=` fields are ignored (no error).
"""

import pytest

from apps.appointments.models import Appointment
from apps.ars.models import ARS
from apps.centers.models import DoctorCenterBinding, MedicalCenter
from apps.doctors.models import DoctorProfile
from apps.medicines.models import Medicine
from apps.patients.models import Patient
from apps.records.models import MedicalRecord


def _patient(**overrides):
    data = {
        "first_name": "Ana",
        "last_name": "Perez",
        "gender": "FEMALE",
        "cedula": "01001084920",
        "nss": "12345678901",
    }
    data.update(overrides)
    return Patient.objects.create(**data)


@pytest.fixture
def mixed_patients(db):
    _patient()
    _patient(
        first_name="Luis", last_name="Perez", cedula="00112345678", nss="98765432109"
    )
    _patient(
        first_name="Ana", last_name="Lopez", cedula="99900011122", nss="55544433321"
    )


# ---------------------------------------------------------------------------
# patients: search
# ---------------------------------------------------------------------------


def test_patient_search_by_name(auth_client, admin_user, mixed_patients):
    res = auth_client(admin_user).get("/api/patients/?search=perez&page_size=20")
    assert res.status_code == 200
    assert {r["full_name"] for r in res.data["results"]} == {"Ana Perez", "Luis Perez"}


def test_patient_search_terms_are_and_ed(auth_client, admin_user, mixed_patients):
    res = auth_client(admin_user).get("/api/patients/?search=ana%20perez&page_size=20")
    assert {r["full_name"] for r in res.data["results"]} == {"Ana Perez"}


def test_patient_search_by_cedula(auth_client, admin_user, mixed_patients):
    res = auth_client(admin_user).get("/api/patients/?search=0100108492&page_size=20")
    assert {r["full_name"] for r in res.data["results"]} == {"Ana Perez"}


def test_patient_search_by_nss(auth_client, admin_user, mixed_patients):
    res = auth_client(admin_user).get("/api/patients/?search=555444333&page_size=20")
    assert {r["full_name"] for r in res.data["results"]} == {"Ana Lopez"}


def test_patient_search_disabled_for_masked_role(auth_client, it_user, mixed_patients):
    # IT must not be able to probe whether a name/cedula/nss is a patient.
    res = auth_client(it_user).get("/api/patients/?search=perez&page_size=20")
    assert res.status_code == 200
    assert res.data["count"] == 3  # search ignored, list unfiltered


# ---------------------------------------------------------------------------
# patients: ordering
# ---------------------------------------------------------------------------


def test_patient_ordering_plaintext_field(auth_client, admin_user, mixed_patients):
    res = auth_client(admin_user).get("/api/patients/?ordering=-search_name&page_size=20")
    names = [r["full_name"] for r in res.data["results"]]
    assert names == sorted(names, reverse=True)


def test_patient_ordering_by_related_ars_name(auth_client, admin_user, db):
    # ars_id "SE"/"SM" are already seeded by a data migration, so use free ids.
    a1 = ARS.objects.create(ars_id="AA", name="Alpha")
    a2 = ARS.objects.create(ars_id="ZZ", name="Zulu")
    _patient(first_name="Bee", last_name="B", ars=a1)
    _patient(first_name="Abe", last_name="A", ars=a2)
    res = auth_client(admin_user).get("/api/patients/?ordering=ars__name&page_size=20")
    assert res.data["results"][0]["full_name"] == "Bee B"
    res = auth_client(admin_user).get("/api/patients/?ordering=-ars__name&page_size=20")
    assert res.data["results"][0]["full_name"] == "Abe A"


def test_patient_ordering_encrypted_cedula_sorted_in_python(
    auth_client, admin_user, mixed_patients
):
    res = auth_client(admin_user).get("/api/patients/?ordering=cedula&page_size=20")
    cedulas = [r["cedula"] for r in res.data["results"]]
    assert cedulas == sorted(cedulas)
    res = auth_client(admin_user).get("/api/patients/?ordering=-cedula&page_size=20")
    cedulas = [r["cedula"] for r in res.data["results"]]
    assert cedulas == sorted(cedulas, reverse=True)


def test_patient_ordering_by_age_sorted_in_python(auth_client, admin_user, db):
    _patient(first_name="Young", last_name="A", birth_date="2010-01-01")
    _patient(first_name="Old", last_name="B", birth_date="1970-01-01")
    res = auth_client(admin_user).get("/api/patients/?ordering=age&page_size=20")
    assert [r["age"] for r in res.data["results"]] == [16, 56]
    res = auth_client(admin_user).get("/api/patients/?ordering=-age&page_size=20")
    assert [r["age"] for r in res.data["results"]] == [56, 16]


def test_patient_invalid_ordering_ignored(auth_client, admin_user, mixed_patients):
    res = auth_client(admin_user).get("/api/patients/?ordering=password&page_size=20")
    assert res.status_code == 200
    assert res.data["count"] == 3


# ---------------------------------------------------------------------------
# records: search by title / patient name / patient cedula / patient nss
# ---------------------------------------------------------------------------


@pytest.fixture
def records_setup(db, doctor_user):
    ana = _patient()
    luis = _patient(
        first_name="Luis", last_name="Perez", cedula="00112345678", nss="98765432109"
    )
    MedicalRecord.objects.create(
        patient=ana, created_by=doctor_user, title="Consulta general"
    )
    MedicalRecord.objects.create(
        patient=luis, created_by=doctor_user, title="Control"
    )


def test_record_search_by_title(auth_client, doctor_user, records_setup):
    res = auth_client(doctor_user).get("/api/medical-records/?search=consulta")
    assert [r["title"] for r in res.data["results"]] == ["Consulta general"]


def test_record_search_by_patient_name(auth_client, doctor_user, records_setup):
    res = auth_client(doctor_user).get("/api/medical-records/?search=luis")
    assert len(res.data["results"]) == 1
    assert res.data["results"][0]["patient_info"]["full_name"] == "Luis Perez"


def test_record_search_by_patient_cedula(auth_client, doctor_user, records_setup):
    res = auth_client(doctor_user).get("/api/medical-records/?search=0100108492")
    assert {r["patient_info"]["full_name"] for r in res.data["results"]} == {
        "Ana Perez"
    }


def test_record_search_by_patient_nss(auth_client, doctor_user, records_setup):
    res = auth_client(doctor_user).get("/api/medical-records/?search=987654321")
    assert {r["patient_info"]["full_name"] for r in res.data["results"]} == {
        "Luis Perez"
    }


def test_record_search_masked_role_title_only(auth_client, it_user, records_setup):
    # IT can search by title but not by patient name/cedula/nss.
    assert auth_client(it_user).get("/api/medical-records/?search=luis").data["count"] == 0
    res = auth_client(it_user).get("/api/medical-records/?search=consulta")
    assert res.data["count"] == 1


def test_record_ordering(auth_client, doctor_user, records_setup):
    res = auth_client(doctor_user).get("/api/medical-records/?ordering=title")
    assert [r["title"] for r in res.data["results"]] == sorted(
        [r["title"] for r in res.data["results"]]
    )


def test_record_exposes_patient_cedula_and_nss(auth_client, doctor_user, records_setup):
    res = auth_client(doctor_user).get("/api/medical-records/?search=ana")
    assert res.data["results"][0]["patient_info"]["cedula"] == "01001084920"
    assert res.data["results"][0]["patient_info"]["nss"] == "12345678901"


def test_record_masks_patient_pii_for_masked_role(auth_client, it_user, records_setup):
    res = auth_client(it_user).get("/api/medical-records/?search=consulta")
    info = res.data["results"][0]["patient_info"]
    assert "01001084920" not in info["cedula"]
    assert "12345678901" not in info["nss"]


# ---------------------------------------------------------------------------
# other endpoints: search + ordering smoke
# ---------------------------------------------------------------------------


def test_centers_search_and_ordering(auth_client, admin_user, db):
    MedicalCenter.objects.create(
        name="Clinica Alpha", code="C1", address="Calle 1", phone="8095550100"
    )
    MedicalCenter.objects.create(
        name="Hospital Beta", code="C2", address="Calle 2", phone="8095550101"
    )
    res = auth_client(admin_user).get("/api/centers/?search=clinica")
    assert {r["name"] for r in res.data["results"]} == {"Clinica Alpha"}
    res = auth_client(admin_user).get("/api/centers/?ordering=-name")
    assert [r["name"] for r in res.data["results"]] == [
        "Hospital Beta",
        "Clinica Alpha",
    ]


def test_centers_ordering_by_doctor_count(auth_client, admin_user, db, doctor_user):
    c1 = MedicalCenter.objects.create(
        name="Alpha", code="A1", address="Calle 1", phone="8095550001"
    )
    c2 = MedicalCenter.objects.create(
        name="Beta", code="B2", address="Calle 2", phone="8095550002"
    )
    prof = DoctorProfile.objects.create(
        user=doctor_user,
        specialty="GP",
        license_number="LIC1",
        contact_phone="8095550000",
    )
    DoctorCenterBinding.objects.create(
        doctor=prof, center=c1, approved=True, approved_by=admin_user
    )
    res = auth_client(admin_user).get("/api/centers/?ordering=doctor_count")
    assert [r["name"] for r in res.data["results"]] == ["Beta", "Alpha"]


def test_doctors_search_and_ordering(auth_client, admin_user, db, make_user):
    u1 = make_user("docA", "DOCTOR", first_name="Zoe", last_name="A")
    u2 = make_user("docB", "DOCTOR", first_name="Abe", last_name="B")
    DoctorProfile.objects.create(
        user=u1, specialty="Cardiologia", license_number="L1", contact_phone="8095550001"
    )
    DoctorProfile.objects.create(
        user=u2, specialty="Pediatria", license_number="L2", contact_phone="8095550002"
    )
    res = auth_client(admin_user).get("/api/doctors/profiles/?search=cardio")
    assert {r["specialty"] for r in res.data["results"]} == {"Cardiologia"}
    res = auth_client(admin_user).get("/api/doctors/profiles/?ordering=-user__last_name")
    assert res.data["results"][0]["full_name"] == "Abe B"


def test_medicines_search_and_ordering(auth_client, admin_user, db):
    Medicine.objects.create(
        generic_name="Amoxicilina", commercial_name="Amox", concentration="500mg"
    )
    Medicine.objects.create(
        generic_name="Ibuprofeno", commercial_name="Brufen", concentration="400mg"
    )
    res = auth_client(admin_user).get("/api/medicines/?search=amoxi")
    assert {r["generic_name"] for r in res.data["results"]} == {"Amoxicilina"}
    res = auth_client(admin_user).get("/api/medicines/?ordering=-generic_name")
    assert [r["generic_name"] for r in res.data["results"]] == [
        "Ibuprofeno",
        "Amoxicilina",
    ]


def test_appointments_search_and_ordering(auth_client, admin_user, db, make_user):
    from datetime import timedelta

    from django.utils import timezone

    doc = make_user("docA", "DOCTOR", first_name="Zoe", last_name="A")
    prof = DoctorProfile.objects.create(
        user=doc, specialty="GP", license_number="L1", contact_phone="8095550001"
    )
    p1 = _patient(first_name="Ana", last_name="Perez")
    p2 = _patient(first_name="Luis", last_name="Perez")
    base = timezone.now()
    Appointment.objects.create(
        patient=p1, doctor=prof, date_time=base, duration_minutes=30, created_by=admin_user
    )
    Appointment.objects.create(
        patient=p2,
        doctor=prof,
        date_time=base + timedelta(hours=1),
        duration_minutes=30,
        created_by=admin_user,
    )
    res = auth_client(admin_user).get("/api/appointments/?search=ana")
    assert len(res.data["results"]) == 1
    res = auth_client(admin_user).get("/api/appointments/?ordering=-date_time")
    assert res.data["results"][0]["patient_info"]["full_name"] == "Luis Perez"


def test_users_search_and_ordering(auth_client, admin_user, db, make_user):
    make_user("zulu", "RECEPTIONIST", first_name="Zoe", last_name="Z")
    make_user("alpha", "NURSE", first_name="Abe", last_name="A")
    res = auth_client(admin_user).get("/api/auth/users/?search=zoe")
    assert {r["username"] for r in res.data["results"]} == {"zulu"}
    res = auth_client(admin_user).get("/api/auth/users/?ordering=-username")
    assert res.data["results"][0]["username"] == "zulu"
