from apps.appointments.models import Appointment
from apps.centers.models import DoctorCenterBinding, MedicalCenter
from apps.doctors.models import DoctorProfile
from apps.medicines.models import Medicine
from apps.patients.models import Patient
from apps.records.models import MedicalRecord, RecordEntry
from apps.services.models import Service, ServiceType


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


def _make_service():
    service_type = ServiceType.objects.get_or_create(name="CONSULTA")[0]
    return Service.objects.create(
        simon="100001", name="Consulta general", type=service_type, co_pago=0, privado=0
    )


def _make_record(patient, doctor_user, **overrides):
    return MedicalRecord.objects.create(
        patient=patient,
        created_by=doctor_user,
        **overrides,
    )


def test_doctor_creates_record(auth_client, doctor_user, receptionist_user):
    patient = _make_patient(receptionist_user)
    res = auth_client(doctor_user).post(
        "/api/medical-records/",
        {"patient": patient.id},
        format="json",
    )
    assert res.status_code == 201
    assert MedicalRecord.objects.count() == 1


def test_receptionist_cannot_create_record(auth_client, receptionist_user):
    patient = _make_patient(receptionist_user)
    res = auth_client(receptionist_user).post(
        "/api/medical-records/",
        {"patient": patient.id},
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
    record = _make_record(patient, doctor_user)
    RecordEntry.objects.create(
        record=record, author=doctor_user, status=RecordEntry.Status.COMPLETED, dx="Hypertension",
    )
    res = auth_client(doctor_user).get("/api/record-entries/")
    assert res.status_code == 200
    result = res.data["results"][0]
    assert result["dx"] == "Hypertension"


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


def test_record_entry_creation(auth_client, doctor_user, receptionist_user):
    patient = _make_patient(receptionist_user)
    record = _make_record(patient, doctor_user)
    res = auth_client(doctor_user).post(
        "/api/record-entries/",
        {"record": record.id, "dx": "Headaches for 2 weeks", "tx": "MRI"},
        format="json",
    )
    assert res.status_code == 201
    entry = RecordEntry.objects.get()
    assert entry.author == doctor_user


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
    service = _make_service()
    res = auth_client(receptionist_user).post(
        "/api/appointments/",
        {
            "patient": patient.id,
            "doctor": doctor.id,
            "service": service.id,
            "date_time": "2099-01-10T09:00:00Z",
        },
        format="json",
    )
    assert res.status_code == 201, res.data
    appt = Appointment.objects.get()
    assert appt.created_by == receptionist_user


def test_nurse_can_create_appointment(auth_client, nurse_user, receptionist_user, doctor_user):
    # NURSE was widened onto CanManageAppointments alongside
    # DOCTOR/RECEPTIONIST/ADMIN.
    patient = _make_patient(receptionist_user)
    doctor = _make_doctor(doctor_user)
    service = _make_service()
    res = auth_client(nurse_user).post(
        "/api/appointments/",
        {
            "patient": patient.id,
            "doctor": doctor.id,
            "service": service.id,
            "date_time": "2099-01-10T09:00:00Z",
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
        date_time="2099-01-10T09:00:00Z",
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
        date_time="2099-01-10T09:00:00Z",
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
        date_time="2099-01-10T09:00:00Z",
        created_by=receptionist_user,
    )
    client = auth_client(doctor_user)

    res = client.patch(f"/api/appointments/{appt.id}/", {"duration_minutes": 45}, format="json")
    assert res.status_code == 403

    res = client.post(f"/api/appointments/{appt.id}/confirm/")
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
        date_time="2099-01-10T09:00:00Z",
        created_by=receptionist_user,
    )
    client = auth_client(doctor_user)

    res = client.patch(f"/api/appointments/{appt.id}/", {"duration_minutes": 45}, format="json")
    assert res.status_code == 200

    res = client.post(f"/api/appointments/{appt.id}/confirm/")
    assert res.status_code == 200
    appt.refresh_from_db()
    assert appt.status == Appointment.Status.CONFIRMED

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
        date_time="2099-01-10T09:00:00Z",
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
        date_time="2099-01-10T09:00:00Z",
        created_by=receptionist_user,
    )
    res = auth_client(it_user).post(f"/api/appointments/{appt.id}/cancel/", {"reason": "Patient request"}, format="json")
    assert res.status_code in (401, 403)
    res = auth_client(receptionist_user).post(f"/api/appointments/{appt.id}/cancel/", {"reason": "Patient request"}, format="json")
    assert res.status_code == 200, res.data
    appt.refresh_from_db()
    assert appt.status == Appointment.Status.CANCELLED
    assert appt.cancel_reason == "Patient request"


def test_cancel_appointment_requires_non_empty_reason(
    auth_client, receptionist_user, doctor_user
):
    patient = _make_patient(receptionist_user)
    doctor = _make_doctor(doctor_user)
    appt = Appointment.objects.create(
        patient=patient,
        doctor=doctor,
        date_time="2099-01-10T09:00:00Z",
        created_by=receptionist_user,
    )
    res = auth_client(receptionist_user).post(f"/api/appointments/{appt.id}/cancel/", {}, format="json")
    assert res.status_code == 400, res.data
    res = auth_client(receptionist_user).post(
        f"/api/appointments/{appt.id}/cancel/", {"reason": "   "}, format="json"
    )
    assert res.status_code == 400, res.data
    appt.refresh_from_db()
    assert appt.status == Appointment.Status.SCHEDULED


def test_confirm_appointment_moves_scheduled_to_confirmed(
    auth_client, receptionist_user, doctor_user
):
    patient = _make_patient(receptionist_user)
    doctor = _make_doctor(doctor_user)
    appt = Appointment.objects.create(
        patient=patient,
        doctor=doctor,
        date_time="2099-01-10T09:00:00Z",
        created_by=receptionist_user,
    )
    res = auth_client(receptionist_user).post(f"/api/appointments/{appt.id}/confirm/")
    assert res.status_code == 200, res.data
    appt.refresh_from_db()
    assert appt.status == Appointment.Status.CONFIRMED


def test_confirm_appointment_forbidden_for_it(auth_client, receptionist_user, doctor_user, it_user):
    patient = _make_patient(receptionist_user)
    doctor = _make_doctor(doctor_user)
    appt = Appointment.objects.create(
        patient=patient,
        doctor=doctor,
        date_time="2099-01-10T09:00:00Z",
        created_by=receptionist_user,
    )
    res = auth_client(it_user).post(f"/api/appointments/{appt.id}/confirm/")
    assert res.status_code in (401, 403)
    appt.refresh_from_db()
    assert appt.status == Appointment.Status.SCHEDULED


def test_confirm_appointment_rejected_when_not_scheduled(auth_client, receptionist_user, doctor_user):
    patient = _make_patient(receptionist_user)
    doctor = _make_doctor(doctor_user)
    client = auth_client(receptionist_user)
    for status in (
        Appointment.Status.CONFIRMED,
        Appointment.Status.COMPLETED,
        Appointment.Status.CANCELLED,
    ):
        appt = Appointment.objects.create(
            patient=patient,
            doctor=doctor,
            date_time="2099-01-10T09:00:00Z",
            status=status,
            created_by=receptionist_user,
        )
        res = client.post(f"/api/appointments/{appt.id}/confirm/")
        assert res.status_code == 400, res.data
        appt.refresh_from_db()
        assert appt.status == status


def test_complete_appointment_rejected_when_not_confirmed(auth_client, receptionist_user, doctor_user):
    """`complete` now requires the two-step Scheduled -> Confirmed ->
    Completed flow -- a direct Scheduled -> Completed call is no longer
    allowed (was previously permissive to any non-terminal status)."""
    patient = _make_patient(receptionist_user)
    doctor = _make_doctor(doctor_user)
    appt = Appointment.objects.create(
        patient=patient,
        doctor=doctor,
        date_time="2099-01-10T09:00:00Z",
        created_by=receptionist_user,
    )
    res = auth_client(receptionist_user).post(f"/api/appointments/{appt.id}/complete/")
    assert res.status_code == 400, res.data
    appt.refresh_from_db()
    assert appt.status == Appointment.Status.SCHEDULED


def test_reschedule_and_cancel_still_allowed_while_confirmed(
    auth_client, receptionist_user, doctor_user
):
    patient = _make_patient(receptionist_user)
    doctor = _make_doctor(doctor_user)
    appt = Appointment.objects.create(
        patient=patient,
        doctor=doctor,
        date_time="2099-01-10T09:00:00Z",
        status=Appointment.Status.CONFIRMED,
        created_by=receptionist_user,
    )
    client = auth_client(receptionist_user)
    res = client.post(
        f"/api/appointments/{appt.id}/reschedule/",
        {"date_time": "2099-01-11T10:30:00Z"},
        format="json",
    )
    assert res.status_code == 200, res.data
    appt.refresh_from_db()
    assert appt.status == Appointment.Status.CONFIRMED

    res = client.post(f"/api/appointments/{appt.id}/cancel/", {"reason": "Patient request"}, format="json")
    assert res.status_code == 200, res.data
    appt.refresh_from_db()
    assert appt.status == Appointment.Status.CANCELLED


def test_create_appointment_requires_service(auth_client, receptionist_user, doctor_user):
    patient = _make_patient(receptionist_user)
    doctor = _make_doctor(doctor_user)
    res = auth_client(receptionist_user).post(
        "/api/appointments/",
        {"patient": patient.id, "doctor": doctor.id, "date_time": "2099-01-10T09:00:00Z"},
        format="json",
    )
    assert res.status_code == 400, res.data
    assert "service" in res.data


def test_create_appointment_defaults_center_to_org_default(
    auth_client, receptionist_user, doctor_user
):
    MedicalCenter.objects.create(
        name="Central", code="C1", address="Addr", phone="8095550000", is_default=True
    )
    patient = _make_patient(receptionist_user)
    doctor = _make_doctor(doctor_user)
    service = _make_service()
    res = auth_client(receptionist_user).post(
        "/api/appointments/",
        {
            "patient": patient.id,
            "doctor": doctor.id,
            "service": service.id,
            "date_time": "2099-01-10T09:00:00Z",
        },
        format="json",
    )
    assert res.status_code == 201, res.data
    assert res.data["center_name"] == "Central"


def test_reschedule_appointment_updates_date_time_only(
    auth_client, receptionist_user, doctor_user
):
    patient = _make_patient(receptionist_user)
    doctor = _make_doctor(doctor_user)
    appt = Appointment.objects.create(
        patient=patient,
        doctor=doctor,
        date_time="2099-01-10T09:00:00Z",
        duration_minutes=45,
        created_by=receptionist_user,
    )
    res = auth_client(receptionist_user).post(
        f"/api/appointments/{appt.id}/reschedule/",
        {"date_time": "2099-01-11T10:30:00Z"},
        format="json",
    )
    assert res.status_code == 200, res.data
    appt.refresh_from_db()
    assert appt.date_time.isoformat() == "2099-01-11T10:30:00+00:00"
    assert appt.duration_minutes == 45


def test_reschedule_forbidden_for_closed_appointment(
    auth_client, receptionist_user, doctor_user
):
    patient = _make_patient(receptionist_user)
    doctor = _make_doctor(doctor_user)
    appt = Appointment.objects.create(
        patient=patient,
        doctor=doctor,
        date_time="2099-01-10T09:00:00Z",
        status=Appointment.Status.CANCELLED,
        created_by=receptionist_user,
    )
    res = auth_client(receptionist_user).post(
        f"/api/appointments/{appt.id}/reschedule/",
        {"date_time": "2099-01-11T10:30:00Z"},
        format="json",
    )
    assert res.status_code == 400, res.data
