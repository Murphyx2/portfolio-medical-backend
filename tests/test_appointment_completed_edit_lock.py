"""Once an Appointment is COMPLETED or CANCELLED, only ADMIN/CENTER_MANAGER
may still edit it (apps/core/permissions.py::CanManageAppointments,
Appointment.is_locked_for_edit()). Doctor/nurse/receptionist keep write
access for every other status."""

from django.utils import timezone

from apps.appointments.models import Appointment
from apps.doctors.models import DoctorProfile
from apps.patients.models import Patient


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


def _appointment(patient, doctor, created_by, **overrides):
    data = {
        "patient": patient,
        "doctor": doctor,
        "date_time": timezone.now(),
        "status": Appointment.Status.SCHEDULED,
        "created_by": created_by,
    }
    data.update(overrides)
    return Appointment.objects.create(**data)


def test_receptionist_cannot_edit_completed_appointment(auth_client, doctor_user, receptionist_user):
    doctor = _doctor(doctor_user)
    appt = _appointment(_patient(), doctor, receptionist_user, status=Appointment.Status.COMPLETED)
    res = auth_client(receptionist_user).patch(f"/api/appointments/{appt.id}/", {"notes": "edited"}, format="json")
    assert res.status_code == 403, res.data


def test_receptionist_cannot_edit_cancelled_appointment(auth_client, doctor_user, receptionist_user):
    doctor = _doctor(doctor_user)
    appt = _appointment(
        _patient(), doctor, receptionist_user,
        status=Appointment.Status.CANCELLED, cancel_reason="No-show",
    )
    res = auth_client(receptionist_user).patch(f"/api/appointments/{appt.id}/", {"notes": "edited"}, format="json")
    assert res.status_code == 403, res.data


def test_doctor_cannot_edit_completed_appointment(auth_client, doctor_user, receptionist_user):
    doctor = _doctor(doctor_user)
    appt = _appointment(_patient(), doctor, receptionist_user, status=Appointment.Status.COMPLETED)
    res = auth_client(doctor_user).patch(f"/api/appointments/{appt.id}/", {"notes": "edited"}, format="json")
    assert res.status_code == 403, res.data


def test_nurse_cannot_edit_completed_appointment(auth_client, doctor_user, nurse_user, receptionist_user):
    doctor = _doctor(doctor_user)
    appt = _appointment(_patient(), doctor, receptionist_user, status=Appointment.Status.COMPLETED)
    res = auth_client(nurse_user).patch(f"/api/appointments/{appt.id}/", {"notes": "edited"}, format="json")
    assert res.status_code == 403, res.data


def test_admin_can_edit_completed_appointment(auth_client, admin_user, doctor_user, receptionist_user):
    doctor = _doctor(doctor_user)
    appt = _appointment(_patient(), doctor, receptionist_user, status=Appointment.Status.COMPLETED)
    res = auth_client(admin_user).patch(f"/api/appointments/{appt.id}/", {"notes": "edited"}, format="json")
    assert res.status_code == 200, res.data
    appt.refresh_from_db()
    assert appt.notes == "edited"


def test_center_manager_can_edit_completed_appointment(auth_client, center_manager_user, doctor_user, receptionist_user):
    doctor = _doctor(doctor_user)
    appt = _appointment(_patient(), doctor, receptionist_user, status=Appointment.Status.COMPLETED)
    res = auth_client(center_manager_user).patch(f"/api/appointments/{appt.id}/", {"notes": "edited"}, format="json")
    assert res.status_code == 200, res.data
    appt.refresh_from_db()
    assert appt.notes == "edited"


def test_center_manager_can_edit_cancelled_appointment(auth_client, center_manager_user, doctor_user, receptionist_user):
    doctor = _doctor(doctor_user)
    appt = _appointment(
        _patient(), doctor, receptionist_user,
        status=Appointment.Status.CANCELLED, cancel_reason="No-show",
    )
    res = auth_client(center_manager_user).patch(f"/api/appointments/{appt.id}/", {"notes": "edited"}, format="json")
    assert res.status_code == 200, res.data


def test_reschedule_on_cancelled_appointment_still_returns_domain_400(auth_client, doctor_user, receptionist_user):
    """The generic edit lock must not shadow reschedule's own "already
    closed" validation (view.action == "reschedule" isn't in the locked
    action set) -- receptionist still reaches the 400, not a 403."""
    doctor = _doctor(doctor_user)
    appt = _appointment(
        _patient(), doctor, receptionist_user,
        status=Appointment.Status.CANCELLED, cancel_reason="No-show",
    )
    res = auth_client(receptionist_user).post(
        f"/api/appointments/{appt.id}/reschedule/", {"date_time": timezone.now().isoformat()}, format="json"
    )
    assert res.status_code == 400, res.data


def test_receptionist_can_still_edit_scheduled_appointment(auth_client, doctor_user, receptionist_user):
    doctor = _doctor(doctor_user)
    appt = _appointment(_patient(), doctor, receptionist_user, status=Appointment.Status.SCHEDULED)
    res = auth_client(receptionist_user).patch(f"/api/appointments/{appt.id}/", {"notes": "edited"}, format="json")
    assert res.status_code == 200, res.data
    appt.refresh_from_db()
    assert appt.notes == "edited"
