"""AppointmentSerializer.validate_date_time: reject a past date_time on
create/update, but only when the value actually changes -- editing other
fields on an already-past appointment must keep working (see
apps/appointments/serializers.py)."""

from datetime import timedelta

from django.utils import timezone

from apps.appointments.models import Appointment
from apps.doctors.models import DoctorProfile
from apps.patients.models import Patient
from apps.services.models import Service, ServiceType


def _patient():
    return Patient.objects.create(
        first_name="Jane", last_name="Doe", gender="FEMALE",
        phone="555-0100", address="123 Main St", email="jane@example.com",
    )


def _doctor(user):
    return DoctorProfile.objects.create(user=user, license_number=f"LIC-{user.id}", contact_phone="555-0000")


def _service():
    service_type = ServiceType.objects.get_or_create(name="CONSULTA")[0]
    return Service.objects.create(simon="100001", name="Consulta general", type=service_type, co_pago=0, privado=0)


def _future(**kwargs):
    return (timezone.now() + timedelta(days=1, **kwargs)).isoformat()


def _past(**kwargs):
    return (timezone.now() - timedelta(days=1, **kwargs)).isoformat()


def test_create_appointment_with_past_date_rejected(auth_client, receptionist_user, doctor_user):
    patient = _patient()
    doctor = _doctor(doctor_user)
    service = _service()
    res = auth_client(receptionist_user).post(
        "/api/appointments/",
        {"patient": patient.id, "doctor": doctor.id, "service": service.id, "date_time": _past()},
        format="json",
    )
    assert res.status_code == 400, res.data
    assert Appointment.objects.count() == 0


def test_create_appointment_with_future_date_allowed(auth_client, receptionist_user, doctor_user):
    patient = _patient()
    doctor = _doctor(doctor_user)
    service = _service()
    res = auth_client(receptionist_user).post(
        "/api/appointments/",
        {"patient": patient.id, "doctor": doctor.id, "service": service.id, "date_time": _future()},
        format="json",
    )
    assert res.status_code == 201, res.data


def test_edit_notes_on_past_appointment_without_changing_date_allowed(
    auth_client, receptionist_user, doctor_user
):
    patient = _patient()
    doctor = _doctor(doctor_user)
    # Within the no-show auto-cancel grace window (12h, apps/appointments/
    # services.py::NO_SHOW_GRACE) so the appointment stays SCHEDULED --
    # a longer-past date_time would get lazily auto-cancelled as a no-show
    # by AppointmentViewSet.get_queryset() before this PATCH's permission
    # check runs, which would then correctly 403 under the CANCELLED edit
    # lock (a different behavior than what this test is exercising).
    appt = Appointment.objects.create(
        patient=patient, doctor=doctor,
        date_time=(timezone.now() - timedelta(hours=6)).isoformat(),
        created_by=receptionist_user,
    )
    res = auth_client(receptionist_user).patch(
        f"/api/appointments/{appt.id}/", {"notes": "Updated notes"}, format="json"
    )
    assert res.status_code == 200, res.data
    appt.refresh_from_db()
    assert appt.notes == "Updated notes"


def test_edit_date_time_to_past_value_rejected(auth_client, receptionist_user, doctor_user):
    patient = _patient()
    doctor = _doctor(doctor_user)
    appt = Appointment.objects.create(
        patient=patient, doctor=doctor, date_time=_future(), created_by=receptionist_user,
    )
    res = auth_client(receptionist_user).patch(
        f"/api/appointments/{appt.id}/", {"date_time": _past()}, format="json"
    )
    assert res.status_code == 400, res.data
    appt.refresh_from_db()
    assert appt.date_time.isoformat() != _past()


def test_reschedule_to_past_date_rejected(auth_client, receptionist_user, doctor_user):
    patient = _patient()
    doctor = _doctor(doctor_user)
    appt = Appointment.objects.create(
        patient=patient, doctor=doctor, date_time=_future(), created_by=receptionist_user,
    )
    res = auth_client(receptionist_user).post(
        f"/api/appointments/{appt.id}/reschedule/", {"date_time": _past()}, format="json"
    )
    assert res.status_code == 400, res.data
    appt.refresh_from_db()
    assert appt.status == Appointment.Status.SCHEDULED


def test_reschedule_to_future_date_allowed(auth_client, receptionist_user, doctor_user):
    patient = _patient()
    doctor = _doctor(doctor_user)
    appt = Appointment.objects.create(
        patient=patient, doctor=doctor, date_time=_future(), created_by=receptionist_user,
    )
    new_date = _future(hours=5)
    res = auth_client(receptionist_user).post(
        f"/api/appointments/{appt.id}/reschedule/", {"date_time": new_date}, format="json"
    )
    assert res.status_code == 200, res.data
