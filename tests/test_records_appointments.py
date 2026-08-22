from apps.appointments.models import Appointment
from apps.centers.models import DoctorCenterBinding, MedicalCenter
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


def test_receptionist_cannot_read_records(auth_client, receptionist_user, doctor_user):
    # Records access was narrowed to ADMIN/DOCTOR/NURSE only -- RECEPTIONIST
    # is blocked outright now instead of getting a redacted read.
    patient = _make_patient(receptionist_user)
    _make_record(patient, doctor_user)
    res = auth_client(receptionist_user).get("/api/medical-records/")
    assert res.status_code == 403


def test_doctor_reads_full_clinical(auth_client, doctor_user, receptionist_user):
    patient = _make_patient(receptionist_user)
    _make_record(patient, doctor_user)
    res = auth_client(doctor_user).get("/api/medical-records/")
    assert res.status_code == 200
    result = res.data["results"][0]
    assert result["diagnosis"] == "Hypertension"


def test_it_cannot_read_records(auth_client, it_user, doctor_user, receptionist_user):
    # Formerly a B6 masking regression guard for IT's read access; records
    # access was later narrowed to ADMIN/DOCTOR/NURSE only, so IT is now
    # blocked outright before the masking logic would ever run.
    patient = _make_patient(receptionist_user)
    patient.cedula = "00112345678"
    patient.save()
    _make_record(patient, doctor_user)

    res = auth_client(it_user).get("/api/medical-records/")
    assert res.status_code == 403


def test_record_patient_info_full_for_doctor(auth_client, doctor_user, receptionist_user):
    patient = _make_patient(receptionist_user)
    patient.cedula = "00112345678"
    patient.save()
    _make_record(patient, doctor_user)

    res = auth_client(doctor_user).get("/api/medical-records/")
    assert res.status_code == 200
    patient_info = res.data["results"][0]["patient_info"]
    assert patient_info["full_name"] == patient.full_name
    assert patient_info["cedula"] == "00112345678"


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


def test_nurse_can_create_appointment(auth_client, nurse_user, receptionist_user, doctor_user):
    # NURSE was widened onto CanManageAppointments alongside
    # DOCTOR/RECEPTIONIST/ADMIN.
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
    assert res.status_code == 201, res.data


def test_appointment_patient_info_masked_for_it_role(
    auth_client, it_user, receptionist_user, doctor_user
):
    """B6 regression guard: AppointmentSerializer's shared PatientLiteSerializer
    still masks only full_name on the nested patient_info for IT (its own
    narrower masked_nested spec, distinct from records' full_name/cedula/nss)."""
    patient = _make_patient(receptionist_user)
    doctor = _make_doctor(doctor_user)
    Appointment.objects.create(
        patient=patient,
        doctor=doctor,
        date_time="2026-08-10T09:00:00Z",
        created_by=receptionist_user,
    )
    res = auth_client(it_user).get("/api/appointments/")
    assert res.status_code == 200
    patient_info = res.data["results"][0]["patient_info"]
    assert patient_info["full_name"] != patient.full_name
    assert patient_info["gender"] == "FEMALE"  # not masked -- outside masked_nested


def test_doctor_sees_colleagues_appointment_at_shared_center(
    auth_client, doctor_user, receptionist_user, admin_user, make_user
):
    """A doctor bound to a center sees another doctor's appointment at that
    same center (matching Patients/Records center-shared scoping), not just
    appointments for themself."""
    from apps.accounts.models import User

    patient = _make_patient(receptionist_user)
    center = MedicalCenter.objects.create(
        name="Central", code="C1", address="Addr", phone="8095550000"
    )
    own_doctor = _make_doctor(doctor_user)
    DoctorCenterBinding.objects.create(
        doctor=own_doctor, center=center, approved=True, approved_by=admin_user
    )
    other_user = make_user("doctor2", User.Role.DOCTOR)
    other_doctor = _make_doctor(other_user)
    Appointment.objects.create(
        patient=patient,
        doctor=other_doctor,
        center=center,
        date_time="2026-08-10T09:00:00Z",
        created_by=receptionist_user,
    )
    res = auth_client(doctor_user).get("/api/appointments/")
    assert res.data["count"] == 1


def test_doctor_cannot_write_colleagues_appointment_at_shared_center(
    auth_client, doctor_user, receptionist_user, admin_user, make_user
):
    """A doctor who can now SEE a colleague's appointment at a shared center
    (test_doctor_sees_colleagues_appointment_at_shared_center) must not be
    able to PATCH, complete, or DELETE it -- read-scope widening must not
    imply write-scope widening (mirrors CanManageEncounters)."""
    from apps.accounts.models import User

    patient = _make_patient(receptionist_user)
    center = MedicalCenter.objects.create(
        name="Central", code="C1", address="Addr", phone="8095550000"
    )
    own_doctor = _make_doctor(doctor_user)
    DoctorCenterBinding.objects.create(
        doctor=own_doctor, center=center, approved=True, approved_by=admin_user
    )
    other_user = make_user("doctor2", User.Role.DOCTOR)
    other_doctor = _make_doctor(other_user)
    appt = Appointment.objects.create(
        patient=patient,
        doctor=other_doctor,
        center=center,
        date_time="2026-08-10T09:00:00Z",
        created_by=receptionist_user,
    )
    client = auth_client(doctor_user)

    res = client.patch(f"/api/appointments/{appt.id}/", {"duration_minutes": 45}, format="json")
    assert res.status_code == 403

    res = client.post(f"/api/appointments/{appt.id}/complete/")
    assert res.status_code == 403

    res = client.delete(f"/api/appointments/{appt.id}/")
    assert res.status_code == 403

    appt.refresh_from_db()
    assert appt.duration_minutes != 45
    assert appt.status != Appointment.Status.COMPLETED
    assert appt.active


def test_doctor_can_write_own_appointment_at_shared_center(
    auth_client, doctor_user, receptionist_user, admin_user
):
    """Sanity check: the object-level fix doesn't block a doctor from
    writing to their own appointment."""
    patient = _make_patient(receptionist_user)
    center = MedicalCenter.objects.create(
        name="Central", code="C1", address="Addr", phone="8095550000"
    )
    own_doctor = _make_doctor(doctor_user)
    DoctorCenterBinding.objects.create(
        doctor=own_doctor, center=center, approved=True, approved_by=admin_user
    )
    appt = Appointment.objects.create(
        patient=patient,
        doctor=own_doctor,
        center=center,
        date_time="2026-08-10T09:00:00Z",
        created_by=receptionist_user,
    )
    client = auth_client(doctor_user)

    res = client.patch(f"/api/appointments/{appt.id}/", {"duration_minutes": 45}, format="json")
    assert res.status_code == 200

    res = client.post(f"/api/appointments/{appt.id}/complete/")
    assert res.status_code == 200
    appt.refresh_from_db()
    assert appt.status == Appointment.Status.COMPLETED


def test_doctor_without_binding_does_not_see_other_centers_appointment(
    auth_client, doctor_user, receptionist_user, admin_user, make_user
):
    """A doctor with no approved binding to a center still sees nothing
    there, even for another doctor's appointment -- only their own rows."""
    from apps.accounts.models import User

    patient = _make_patient(receptionist_user)
    center = MedicalCenter.objects.create(
        name="Central", code="C1", address="Addr", phone="8095550000"
    )
    _make_doctor(doctor_user)
    other_user = make_user("doctor2", User.Role.DOCTOR)
    other_doctor = _make_doctor(other_user)
    Appointment.objects.create(
        patient=patient,
        doctor=other_doctor,
        center=center,
        date_time="2026-08-10T09:00:00Z",
        created_by=receptionist_user,
    )
    res = auth_client(doctor_user).get("/api/appointments/")
    assert res.data["count"] == 0


def test_cancel_appointment_forbidden_for_it(
    auth_client, receptionist_user, doctor_user, it_user
):
    # DOCTOR/NURSE/RECEPTIONIST/ADMIN may cancel; IT (and every other
    # non-listed role) may not.
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
