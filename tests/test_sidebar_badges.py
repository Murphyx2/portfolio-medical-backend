"""Sidebar nav badge counts:

1. GET /api/appointments/today_remaining_count/ -- SCHEDULED/CONFIRMED
   appointments still ahead today, scoped exactly like the list endpoint
   (apps/appointments/views.py::AppointmentViewSet.today_remaining_count).
2. GET /api/communications/messages/?status__in=DRAFT,FAILED -- newly-added
   filterset_fields on MessageViewSet (previously missing entirely, so
   status/kind filters were silently ignored).
"""

from datetime import timedelta

from django.utils import timezone

from apps.appointments.models import Appointment
from apps.communications.models import Message
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


# ---------------------------------------------------------------------------
# today_remaining_count
# ---------------------------------------------------------------------------


def test_today_remaining_count_zero_with_no_appointments(auth_client, receptionist_user):
    res = auth_client(receptionist_user).get("/api/appointments/today_remaining_count/")
    assert res.status_code == 200
    assert res.data["count"] == 0


def test_today_remaining_count_includes_only_scheduled_and_confirmed(
    auth_client, receptionist_user, doctor_user
):
    doctor = _doctor(doctor_user)
    now = timezone.now()
    _appointment(_patient(cedula="00100000001"), doctor, receptionist_user, status=Appointment.Status.SCHEDULED, date_time=now + timedelta(hours=1))
    _appointment(_patient(cedula="00100000002"), doctor, receptionist_user, status=Appointment.Status.CONFIRMED, date_time=now + timedelta(hours=2))
    _appointment(_patient(cedula="00100000003"), doctor, receptionist_user, status=Appointment.Status.COMPLETED, date_time=now + timedelta(hours=3))
    _appointment(_patient(cedula="00100000004"), doctor, receptionist_user, status=Appointment.Status.CANCELLED, date_time=now + timedelta(hours=4))

    res = auth_client(receptionist_user).get("/api/appointments/today_remaining_count/")
    assert res.status_code == 200
    assert res.data["count"] == 2


def test_today_remaining_count_excludes_other_days(auth_client, receptionist_user, doctor_user):
    doctor = _doctor(doctor_user)
    now = timezone.now()
    _appointment(_patient(cedula="00100000005"), doctor, receptionist_user, status=Appointment.Status.SCHEDULED, date_time=now + timedelta(days=1))
    _appointment(_patient(cedula="00100000006"), doctor, receptionist_user, status=Appointment.Status.SCHEDULED, date_time=now - timedelta(hours=1))

    res = auth_client(receptionist_user).get("/api/appointments/today_remaining_count/")
    assert res.status_code == 200
    assert res.data["count"] == 0


def test_today_remaining_count_scoped_to_doctor(auth_client, doctor_user, make_user, receptionist_user):
    from apps.accounts.models import User
    from apps.centers.models import DoctorCenterBinding, MedicalCenter

    other_doctor_user = make_user("other_doc", User.Role.DOCTOR)
    doctor = _doctor(doctor_user)
    other_doctor = _doctor(other_doctor_user)
    center = MedicalCenter.objects.create(name="Center A", code="CA", address="A", phone="1")
    DoctorCenterBinding.objects.create(doctor=doctor, center=center, approved=True)

    now = timezone.now()
    _appointment(_patient(cedula="00100000007"), doctor, receptionist_user, status=Appointment.Status.SCHEDULED, date_time=now + timedelta(hours=1))
    _appointment(_patient(cedula="00100000008"), other_doctor, receptionist_user, status=Appointment.Status.SCHEDULED, date_time=now + timedelta(hours=1))

    res = auth_client(doctor_user).get("/api/appointments/today_remaining_count/")
    assert res.status_code == 200
    assert res.data["count"] == 1


# ---------------------------------------------------------------------------
# communications/messages/ status__in filter
# ---------------------------------------------------------------------------


def test_messages_status_in_filter_returns_only_matching(auth_client, admin_user):
    Message.objects.create(
        channel=Message.Channel.EMAIL, audience=Message.Audience.STAFF,
        kind="AVISO", status=Message.Status.DRAFT, created_by=admin_user,
    )
    Message.objects.create(
        channel=Message.Channel.EMAIL, audience=Message.Audience.STAFF,
        kind="AVISO", status=Message.Status.FAILED, created_by=admin_user,
    )
    Message.objects.create(
        channel=Message.Channel.EMAIL, audience=Message.Audience.STAFF,
        kind="AVISO", status=Message.Status.SENT, created_by=admin_user,
    )

    res = auth_client(admin_user).get(
        "/api/communications/messages/?status__in=DRAFT,FAILED&page_size=1"
    )
    assert res.status_code == 200
    assert res.data["count"] == 2


def test_messages_status_in_filter_scoped_to_creator_for_non_admin(auth_client, doctor_user, make_user):
    from apps.accounts.models import User

    other_admin = make_user("other_admin", User.Role.ADMIN)
    Message.objects.create(
        channel=Message.Channel.EMAIL, audience=Message.Audience.STAFF,
        kind="AVISO", status=Message.Status.DRAFT, created_by=other_admin,
    )
    Message.objects.create(
        channel=Message.Channel.EMAIL, audience=Message.Audience.STAFF,
        kind="AVISO", status=Message.Status.DRAFT, created_by=doctor_user,
    )

    res = auth_client(doctor_user).get(
        "/api/communications/messages/?status__in=DRAFT,FAILED&page_size=1"
    )
    assert res.status_code == 200
    assert res.data["count"] == 1
