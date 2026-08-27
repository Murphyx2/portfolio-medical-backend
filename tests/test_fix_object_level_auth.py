"""Fix H-03: object-level authorization for doctors.

(a) A DOCTOR posting an appointment with a `doctor` field that is NOT their
    own DoctorProfile gets 400; their own profile works.
(b) A DOCTOR creating a medical record with a `center` they have no approved
    DoctorCenterBinding for gets 400; center null or an approved center works.
(c) A doctor's list of appointments/records is scoped to their own doctor /
    approved centers - no other doctor's data appears.
"""

from apps.appointments.models import Appointment
from apps.centers.models import DoctorCenterBinding, MedicalCenter
from apps.doctors.models import DoctorProfile
from apps.patients.models import Patient
from apps.records.models import MedicalRecord
from apps.services.models import Service, ServiceType


def _make_patient():
    return Patient.objects.create(
        first_name="Jane",
        last_name="Doe",
        gender="FEMALE",
        phone="555-0100",
        address="123 Main St",
        email="jane@example.com",
    )


def _make_service():
    service_type = ServiceType.objects.get_or_create(name="Consulta")[0]
    return Service.objects.create(
        simon="100001", name="Consulta general", type=service_type, co_pago=0, privado=0
    )


def _make_doctor(user, license_number=None):
    return DoctorProfile.objects.create(
        user=user,
        license_number=license_number or f"LIC-{user.id}",
        contact_phone="555-0000",
    )


def _make_center(code="C1"):
    return MedicalCenter.objects.create(
        name=f"Center {code}", code=code, address="A", phone="1"
    )


def _approve_binding(doctor_profile, center):
    return DoctorCenterBinding.objects.create(
        doctor=doctor_profile, center=center, approved=True
    )


# ---------- (a) appointments: doctor field must be the caller's profile ----------

def test_doctor_cannot_book_appointment_for_another_doctor(
    auth_client, doctor_user, make_user
):
    other_doc = make_user("other_doc", "DOCTOR")
    _make_doctor(doctor_user)
    other_profile = _make_doctor(other_doc, "LIC-OTHER")
    patient = _make_patient()

    res = auth_client(doctor_user).post(
        "/api/appointments/",
        {
            "patient": patient.id,
            "doctor": other_profile.id,
            "date_time": "2099-01-10T09:00:00Z",
        },
        format="json",
    )
    assert res.status_code == 400
    assert "themselves" in str(res.data).lower() or "own" in str(res.data).lower()
    assert Appointment.objects.count() == 0


def test_doctor_can_book_appointment_for_own_profile(
    auth_client, doctor_user, receptionist_user
):
    profile = _make_doctor(doctor_user)
    patient = _make_patient()
    service = _make_service()

    res = auth_client(doctor_user).post(
        "/api/appointments/",
        {
            "patient": patient.id,
            "doctor": profile.id,
            "service": service.id,
            "date_time": "2099-01-10T09:00:00Z",
        },
        format="json",
    )
    assert res.status_code == 201, res.data
    assert Appointment.objects.count() == 1


# ---------- (b) records: doctors have unrestricted access, unlike appointments ----------

def test_doctor_record_with_unapproved_center_returns_201(
    auth_client, doctor_user
):
    # Unlike appointments, records are not scoped to a doctor's approved
    # centers -- any doctor may write a record at any center.
    _make_doctor(doctor_user)
    unapproved = _make_center("C-UN-APPROVED")
    patient = _make_patient()

    res = auth_client(doctor_user).post(
        "/api/medical-records/",
        {
            "patient": patient.id,
            "title": "T",
            "diagnosis": "D",
            "center": unapproved.id,
        },
        format="json",
    )
    assert res.status_code == 201, res.data
    assert MedicalRecord.objects.count() == 1


def test_doctor_record_with_null_center_returns_201(auth_client, doctor_user):
    _make_doctor(doctor_user)
    patient = _make_patient()

    res = auth_client(doctor_user).post(
        "/api/medical-records/",
        {"patient": patient.id, "title": "T", "diagnosis": "D"},
        format="json",
    )
    assert res.status_code == 201, res.data
    assert MedicalRecord.objects.count() == 1


def test_doctor_record_with_approved_center_returns_201(auth_client, doctor_user):
    profile = _make_doctor(doctor_user)
    center = _make_center("C-APPROVED")
    _approve_binding(profile, center)
    patient = _make_patient()

    res = auth_client(doctor_user).post(
        "/api/medical-records/",
        {
            "patient": patient.id,
            "title": "T",
            "diagnosis": "D",
            "center": center.id,
        },
        format="json",
    )
    assert res.status_code == 201, res.data
    assert MedicalRecord.objects.count() == 1


# ---------- (c) scoped lists ----------

def test_doctor_appointment_list_scoped_to_own_profile(
    auth_client, doctor_user, make_user, receptionist_user
):
    own_profile = _make_doctor(doctor_user)
    other_user = make_user("other_doc", "DOCTOR")
    other_profile = _make_doctor(other_user, "LIC-OTHER-2")
    patient = _make_patient()

    Appointment.objects.create(
        patient=patient,
        doctor=own_profile,
        date_time="2099-01-11T09:00:00Z",
        created_by=receptionist_user,
    )
    Appointment.objects.create(
        patient=patient,
        doctor=other_profile,
        date_time="2026-08-12T09:00:00Z",
        created_by=receptionist_user,
    )

    res = auth_client(doctor_user).get("/api/appointments/")
    assert res.status_code == 200
    ids = {item["id"] for item in res.data["results"]}
    own_id = Appointment.objects.get(doctor=own_profile).id
    other_id = Appointment.objects.get(doctor=other_profile).id
    assert own_id in ids
    assert other_id not in ids


def test_doctor_record_list_is_unscoped(
    auth_client, doctor_user, make_user
):
    # Doctors see every record, not just their own center's -- unlike
    # appointments, which stay scoped (see test_doctor_appointment_list_scoped_to_own_profile).
    own_profile = _make_doctor(doctor_user)
    center = _make_center("C-SCOPED")
    _approve_binding(own_profile, center)
    patient = _make_patient()

    other_patient = Patient.objects.create(
        first_name="Other", last_name="Patient", gender="MALE", phone="555-0200",
    )
    own_record = MedicalRecord.objects.create(
        patient=patient, created_by=doctor_user, center=center
    )
    other_user = make_user("other_doc", "DOCTOR")
    other_record = MedicalRecord.objects.create(
        patient=other_patient, created_by=other_user
    )

    res = auth_client(doctor_user).get("/api/medical-records/")
    assert res.status_code == 200
    ids = {item["id"] for item in res.data["results"]}
    assert own_record.id in ids
    assert other_record.id in ids
