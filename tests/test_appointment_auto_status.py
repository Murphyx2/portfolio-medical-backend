"""Two automatic Appointment status rules (no dedicated FK between
Appointment and Encounter -- matched by patient/date only):

1. Admitting an Encounter (DRAFT -> ACTIVE) auto-completes that patient's
   SCHEDULED/CONFIRMED appointment(s) dated the same day as the admission
   (apps/appointments/services.py::complete_todays_appointments_for_patient,
   called from EncounterViewSet.admit).
2. Any SCHEDULED appointment more than 12h past its date_time is lazily
   auto-cancelled the next time anyone reads the appointments endpoint
   (apps/appointments/services.py::cancel_noshow_appointments, called from
   AppointmentViewSet.get_queryset) -- no celery/cron in this repo.
"""

from datetime import timedelta

from django.utils import timezone

from apps.appointments.models import Appointment
from apps.centers.models import MedicalCenter
from apps.doctors.models import DoctorProfile
from apps.encounters.models import Encounter
from apps.patients.models import Patient
from apps.rooms.models import Room, RoomType
from apps.services.models import Service, ServiceType


def _patient(**overrides):
    data = {
        "first_name": "Jane",
        "last_name": "Doe",
        "gender": "FEMALE",
        "birth_date": "1990-01-01",
        "cedula": overrides.pop("cedula", "00100000001"),
    }
    data.update(overrides)
    return Patient.objects.create(**data)


def _doctor(user, **overrides):
    data = {"license_number": f"LIC-{user.id}", "contact_phone": "8095550000"}
    data.update(overrides)
    return DoctorProfile.objects.create(user=user, **data)


def _center(code="C1"):
    return MedicalCenter.objects.create(name=f"Center {code}", code=code, address="A", phone="1")


def _room(center):
    room_type = RoomType.objects.get_or_create(name="Consulta")[0]
    return Room.objects.create(code="R1", name="Room", room_type=room_type, center=center)


def _service_type():
    return ServiceType.objects.get_or_create(name="Consulta General", defaults={"requires_doctor": False})[0]


def _appointment(patient, doctor, receptionist_user, **overrides):
    data = {
        "patient": patient,
        "doctor": doctor,
        "date_time": timezone.now(),
        "status": Appointment.Status.SCHEDULED,
        "created_by": receptionist_user,
    }
    data.update(overrides)
    return Appointment.objects.create(**data)


# ---------------------------------------------------------------------------
# Rule 1: admission auto-completes today's SCHEDULED/CONFIRMED appointments.
# ---------------------------------------------------------------------------


def test_admit_completes_todays_scheduled_appointment(auth_client, admin_user, doctor_user, receptionist_user):
    doctor = _doctor(doctor_user)
    center = _center()
    room = _room(center)
    patient = _patient()
    appt = _appointment(patient, doctor, receptionist_user, status=Appointment.Status.SCHEDULED)
    encounter = Encounter.objects.create(
        service_type=_service_type(), patient=patient, doctor=doctor, room=room, created_by=admin_user,
    )
    res = auth_client(admin_user).post(f"/api/encounters/{encounter.id}/admit/")
    assert res.status_code == 200, res.data
    appt.refresh_from_db()
    assert appt.status == Appointment.Status.COMPLETED


def test_admit_completes_todays_confirmed_appointment(auth_client, admin_user, doctor_user, receptionist_user):
    doctor = _doctor(doctor_user)
    center = _center()
    room = _room(center)
    patient = _patient()
    appt = _appointment(patient, doctor, receptionist_user, status=Appointment.Status.CONFIRMED)
    encounter = Encounter.objects.create(
        service_type=_service_type(), patient=patient, doctor=doctor, room=room, created_by=admin_user,
    )
    res = auth_client(admin_user).post(f"/api/encounters/{encounter.id}/admit/")
    assert res.status_code == 200, res.data
    appt.refresh_from_db()
    assert appt.status == Appointment.Status.COMPLETED


def test_admit_does_not_touch_appointment_on_a_different_day(
    auth_client, admin_user, doctor_user, receptionist_user
):
    doctor = _doctor(doctor_user)
    center = _center()
    room = _room(center)
    patient = _patient()
    appt = _appointment(
        patient, doctor, receptionist_user,
        status=Appointment.Status.SCHEDULED,
        date_time=timezone.now() + timedelta(days=2),
    )
    encounter = Encounter.objects.create(
        service_type=_service_type(), patient=patient, doctor=doctor, room=room, created_by=admin_user,
    )
    res = auth_client(admin_user).post(f"/api/encounters/{encounter.id}/admit/")
    assert res.status_code == 200, res.data
    appt.refresh_from_db()
    assert appt.status == Appointment.Status.SCHEDULED


def test_admit_does_not_touch_already_closed_appointment(
    auth_client, admin_user, doctor_user, receptionist_user
):
    doctor = _doctor(doctor_user)
    center = _center()
    room = _room(center)
    patient = _patient()
    appt = _appointment(patient, doctor, receptionist_user, status=Appointment.Status.CANCELLED)
    encounter = Encounter.objects.create(
        service_type=_service_type(), patient=patient, doctor=doctor, room=room, created_by=admin_user,
    )
    res = auth_client(admin_user).post(f"/api/encounters/{encounter.id}/admit/")
    assert res.status_code == 200, res.data
    appt.refresh_from_db()
    assert appt.status == Appointment.Status.CANCELLED


# ---------------------------------------------------------------------------
# Rule 2: lazy no-show auto-cancel on read (SCHEDULED, >12h past date_time).
# ---------------------------------------------------------------------------


def test_reading_appointments_cancels_stale_scheduled_appointment(
    auth_client, receptionist_user, doctor_user
):
    doctor = _doctor(doctor_user)
    patient = _patient()
    appt = _appointment(
        patient, doctor, receptionist_user,
        status=Appointment.Status.SCHEDULED,
        date_time=timezone.now() - timedelta(hours=13),
    )
    res = auth_client(receptionist_user).get("/api/appointments/")
    assert res.status_code == 200
    appt.refresh_from_db()
    assert appt.status == Appointment.Status.CANCELLED
    assert appt.cancel_reason == "Paciente no se presento a consulta."


def test_appointment_within_grace_period_is_untouched(auth_client, receptionist_user, doctor_user):
    doctor = _doctor(doctor_user)
    patient = _patient()
    appt = _appointment(
        patient, doctor, receptionist_user,
        status=Appointment.Status.SCHEDULED,
        date_time=timezone.now() - timedelta(hours=6),
    )
    res = auth_client(receptionist_user).get("/api/appointments/")
    assert res.status_code == 200
    appt.refresh_from_db()
    assert appt.status == Appointment.Status.SCHEDULED
    assert appt.cancel_reason == ""


def test_confirmed_appointment_is_not_auto_cancelled(auth_client, receptionist_user, doctor_user):
    doctor = _doctor(doctor_user)
    patient = _patient()
    appt = _appointment(
        patient, doctor, receptionist_user,
        status=Appointment.Status.CONFIRMED,
        date_time=timezone.now() - timedelta(hours=13),
    )
    res = auth_client(receptionist_user).get("/api/appointments/")
    assert res.status_code == 200
    appt.refresh_from_db()
    assert appt.status == Appointment.Status.CONFIRMED
