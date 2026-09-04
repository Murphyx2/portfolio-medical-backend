"""apps.appointments.services.check_slot_available + its wiring into
AppointmentSerializer.validate() (RECETAS_REQUIREMENTS.md follow-up task):
two overlapping SCHEDULED/CONFIRMED appointments for the same doctor
conflict; different doctors never conflict; CANCELLED/NO_SHOW/COMPLETED
appointments never occupy a slot; editing unrelated fields on an
already-self-conflicting appointment must not false-positive; editing
date_time to a genuinely free slot must succeed."""

from datetime import timedelta

from django.utils import timezone

from apps.appointments.models import Appointment
from apps.appointments.services import check_slot_available
from apps.doctors.models import DoctorProfile
from apps.patients.models import Patient
from apps.services.models import Service, ServiceType


def _patient(**kwargs):
    defaults = dict(
        first_name="Jane", last_name="Doe", gender="FEMALE",
        phone="555-0100", address="123 Main St", email="jane@example.com",
    )
    defaults.update(kwargs)
    return Patient.objects.create(**defaults)


def _doctor(user):
    return DoctorProfile.objects.create(user=user, license_number=f"LIC-{user.id}", contact_phone="555-0000")


def _service():
    service_type = ServiceType.objects.get_or_create(name="CONSULTA")[0]
    return Service.objects.create(simon="100001", name="Consulta general", type=service_type, co_pago=0, privado=0)


def _future(**kwargs):
    return timezone.now() + timedelta(days=1, **kwargs)


def test_check_slot_available_true_when_no_appointments(doctor_user):
    doctor = _doctor(doctor_user)
    assert check_slot_available(doctor, _future(), 30) is True


def test_overlapping_appointment_same_doctor_conflicts(doctor_user, receptionist_user):
    doctor = _doctor(doctor_user)
    patient = _patient()
    start = _future()
    Appointment.objects.create(
        patient=patient, doctor=doctor, date_time=start, duration_minutes=30,
        created_by=receptionist_user,
    )
    # Overlaps the first appointment's [start, start+30) window.
    overlapping = start + timedelta(minutes=15)
    assert check_slot_available(doctor, overlapping, 30) is False


def test_non_overlapping_appointment_same_doctor_available(doctor_user, receptionist_user):
    doctor = _doctor(doctor_user)
    patient = _patient()
    start = _future()
    Appointment.objects.create(
        patient=patient, doctor=doctor, date_time=start, duration_minutes=30,
        created_by=receptionist_user,
    )
    after = start + timedelta(minutes=30)
    assert check_slot_available(doctor, after, 30) is True


def test_different_doctors_never_conflict(doctor_user, admin_user, receptionist_user):
    doctor1 = _doctor(doctor_user)
    doctor2 = _doctor(admin_user)
    patient = _patient()
    start = _future()
    Appointment.objects.create(
        patient=patient, doctor=doctor1, date_time=start, duration_minutes=30,
        created_by=receptionist_user,
    )
    assert check_slot_available(doctor2, start, 30) is True


def test_cancelled_appointment_does_not_block_slot(doctor_user, receptionist_user):
    doctor = _doctor(doctor_user)
    patient = _patient()
    start = _future()
    Appointment.objects.create(
        patient=patient, doctor=doctor, date_time=start, duration_minutes=30,
        status=Appointment.Status.CANCELLED, created_by=receptionist_user,
    )
    assert check_slot_available(doctor, start, 30) is True


def test_completed_appointment_does_not_block_slot(doctor_user, receptionist_user):
    doctor = _doctor(doctor_user)
    patient = _patient()
    start = _future()
    Appointment.objects.create(
        patient=patient, doctor=doctor, date_time=start, duration_minutes=30,
        status=Appointment.Status.COMPLETED, created_by=receptionist_user,
    )
    assert check_slot_available(doctor, start, 30) is True


def test_no_show_appointment_does_not_block_slot(doctor_user, receptionist_user):
    doctor = _doctor(doctor_user)
    patient = _patient()
    start = _future()
    Appointment.objects.create(
        patient=patient, doctor=doctor, date_time=start, duration_minutes=30,
        status=Appointment.Status.NO_SHOW, created_by=receptionist_user,
    )
    assert check_slot_available(doctor, start, 30) is True


def test_exclude_pk_lets_appointment_edit_ignore_itself(doctor_user, receptionist_user):
    doctor = _doctor(doctor_user)
    patient = _patient()
    start = _future()
    appt = Appointment.objects.create(
        patient=patient, doctor=doctor, date_time=start, duration_minutes=30,
        created_by=receptionist_user,
    )
    assert check_slot_available(doctor, start, 30, exclude_pk=appt.pk) is True
    assert check_slot_available(doctor, start, 30) is False


# -- API-level: AppointmentSerializer.validate() wiring --------------------


def test_create_appointment_api_conflict_rejected(auth_client, receptionist_user, doctor_user):
    doctor = _doctor(doctor_user)
    service = _service()
    start = _future().isoformat()
    patient1 = _patient(cedula="00100000001")
    patient2 = _patient(cedula="00100000002")
    client = auth_client(receptionist_user)
    res1 = client.post(
        "/api/appointments/",
        {"patient": patient1.id, "doctor": doctor.id, "service": service.id, "date_time": start},
        format="json",
    )
    assert res1.status_code == 201, res1.data
    res2 = client.post(
        "/api/appointments/",
        {"patient": patient2.id, "doctor": doctor.id, "service": service.id, "date_time": start},
        format="json",
    )
    assert res2.status_code == 400, res2.data
    assert "date_time" in res2.data


def test_edit_notes_without_changing_date_time_does_not_false_positive(
    auth_client, receptionist_user, doctor_user
):
    doctor = _doctor(doctor_user)
    patient = _patient()
    appt = Appointment.objects.create(
        patient=patient, doctor=doctor, date_time=_future(), created_by=receptionist_user,
    )
    res = auth_client(receptionist_user).patch(
        f"/api/appointments/{appt.id}/", {"notes": "hello"}, format="json"
    )
    assert res.status_code == 200, res.data


def test_edit_date_time_to_free_slot_succeeds(auth_client, receptionist_user, doctor_user):
    doctor = _doctor(doctor_user)
    patient = _patient()
    appt = Appointment.objects.create(
        patient=patient, doctor=doctor, date_time=_future(), created_by=receptionist_user,
    )
    new_slot = _future(hours=5).isoformat()
    res = auth_client(receptionist_user).patch(
        f"/api/appointments/{appt.id}/", {"date_time": new_slot}, format="json"
    )
    assert res.status_code == 200, res.data
