from apps.appointments.models import Appointment
from apps.centers.models import MedicalCenter
from apps.doctors.models import DoctorProfile
from apps.medicines.models import Medicine
from apps.patients.models import Patient
from apps.records.models import ConsultationLog, MedicalRecord


def _make_patient(receptionist_user):
    return Patient.objects.create(
        first_name="Jane",
        last_name="Doe",
        gender="FEMALE",
        phone="555-0100",
        address="123 Main St",
        email="jane@example.com",
    )


def _make_doctor(user):
    return DoctorProfile.objects.create(
        user=user,
        specialty="Cardiology",
        license_number=f"LIC-{user.id}",
        contact_phone="555-0000",
    )


def _make_record(patient, doctor_user, **overrides):
    data = {
        "title": "Follow-up",
        "diagnosis": "Hypertension",
        "treatment": "Lifestyle changes",
        "medicine_and_doses": "Amlodipine 5mg daily",
        "notes": "Monitor weekly",
    }
    data.update(overrides)
    return MedicalRecord.objects.create(
        patient=patient,
        created_by=doctor_user,
        **data,
    )


def test_doctor_creates_record(auth_client, doctor_user, receptionist_user):
    patient = _make_patient(receptionist_user)
    res = auth_client(doctor_user).post(
        "/api/medical-records/",
        {
            "patient": patient.id,
            "title": "Initial consult",
            "diagnosis": "Migraine",
            "notes": "Started new meds",
        },
        format="json",
    )
    assert res.status_code == 201
    assert MedicalRecord.objects.count() == 1


def test_receptionist_cannot_create_record(auth_client, receptionist_user):
    patient = _make_patient(receptionist_user)
    res = auth_client(receptionist_user).post(
        "/api/medical-records/",
        {"patient": patient.id, "title": "x", "diagnosis": "y"},
        format="json",
    )
    assert res.status_code in (401, 403)


def test_receptionist_reads_redacted_clinical(auth_client, receptionist_user, doctor_user):
    patient = _make_patient(receptionist_user)
    _make_record(patient, doctor_user)
    res = auth_client(receptionist_user).get("/api/medical-records/")
    assert res.status_code == 200
    result = res.data["results"][0]
    assert "Hypertension" not in result["diagnosis"]


def test_doctor_reads_full_clinical(auth_client, doctor_user, receptionist_user):
    patient = _make_patient(receptionist_user)
    _make_record(patient, doctor_user)
    res = auth_client(doctor_user).get("/api/medical-records/")
    assert res.status_code == 200
    result = res.data["results"][0]
    assert result["diagnosis"] == "Hypertension"


def test_consultation_log_creation(auth_client, doctor_user, receptionist_user):
    patient = _make_patient(receptionist_user)
    res = auth_client(doctor_user).post(
        "/api/consultation-logs/",
        {"patient": patient.id, "subjective": "Headaches for 2 weeks", "plan": "MRI"},
        format="json",
    )
    assert res.status_code == 201
    log = ConsultationLog.objects.get()
    assert log.doctor == doctor_user


def test_medicine_crud_for_admin(auth_client, admin_user):
    res = auth_client(admin_user).post(
        "/api/medicines/",
        {
            "generic_name": "Amlodipine",
            "commercial_name": "Norvasc",
            "concentration": "5mg",
        },
        format="json",
    )
    assert res.status_code == 201
    assert Medicine.objects.count() == 1


def test_nurse_reads_medicines(auth_client, nurse_user, admin_user):
    auth_client(admin_user).post(
        "/api/medicines/",
        {"generic_name": "Paracetamol", "commercial_name": "Tylenol", "concentration": "500mg"},
        format="json",
    )
    res = auth_client(nurse_user).get("/api/medicines/")
    assert res.status_code == 200
    assert res.data["count"] == 1


def test_appointment_created_by_receptionist(
    auth_client, receptionist_user, doctor_user
):
    patient = _make_patient(receptionist_user)
    doctor = _make_doctor(doctor_user)
    res = auth_client(receptionist_user).post(
        "/api/appointments/",
        {
            "patient": patient.id,
            "doctor": doctor.id,
            "date_time": "2026-08-10T09:00:00Z",
        },
        format="json",
    )
    assert res.status_code == 201
    appt = Appointment.objects.get()
    assert appt.created_by == receptionist_user


def test_nurse_cannot_create_appointment(auth_client, nurse_user, receptionist_user, doctor_user):
    patient = _make_patient(receptionist_user)
    doctor = _make_doctor(doctor_user)
    res = auth_client(nurse_user).post(
        "/api/appointments/",
        {
            "patient": patient.id,
            "doctor": doctor.id,
            "date_time": "2026-08-10T09:00:00Z",
        },
        format="json",
    )
    assert res.status_code in (401, 403)


def test_cancel_appointment_only_receptionist_or_admin(
    auth_client, receptionist_user, doctor_user, it_user
):
    patient = _make_patient(receptionist_user)
    doctor = _make_doctor(doctor_user)
    appt = Appointment.objects.create(
        patient=patient,
        doctor=doctor,
        date_time="2026-08-10T09:00:00Z",
        created_by=receptionist_user,
    )
    res = auth_client(it_user).post(f"/api/appointments/{appt.id}/cancel/")
    assert res.status_code in (401, 403)
    res = auth_client(receptionist_user).post(f"/api/appointments/{appt.id}/cancel/")
    assert res.status_code == 200
    appt.refresh_from_db()
    assert appt.status == Appointment.Status.CANCELLED
