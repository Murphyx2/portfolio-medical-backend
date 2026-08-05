"""Fix H-05: object-level authorization for doctor schedule writes.

(a) A DOCTOR posting a DoctorSchedule with a `doctor` field that is NOT their
    own DoctorProfile gets 400; their own profile works.
(b) A DOCTOR creating a DoctorSchedule with a `center` they have no approved
    DoctorCenterBinding for gets 400; an approved center works.
(c) A doctor's schedule list is scoped to their own DoctorProfile - no other
    doctor's schedules appear.
"""

from apps.centers.models import DoctorCenterBinding, MedicalCenter
from apps.doctors.models import DoctorProfile, DoctorSchedule


def _make_doctor(user, license_number=None):
    return DoctorProfile.objects.create(
        user=user,
        specialty="Cardiology",
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


def _schedule_payload(doctor_profile_id, center_id):
    return {
        "doctor": doctor_profile_id,
        "center": center_id,
        "weekday": 0,
        "start_time": "09:00",
        "end_time": "17:00",
    }


# ---------- (a) schedules: doctor field must be the caller's profile ----------

def test_doctor_cannot_create_schedule_for_another_doctor(
    auth_client, doctor_user, make_user
):
    other_doc = make_user("other_doc_sched", "DOCTOR")
    _make_doctor(doctor_user)
    other_profile = _make_doctor(other_doc, "LIC-SCHED-OTHER")
    center = _make_center("C-SCHED-APPROVED")
    # even with an approved binding for the other doctor, the `doctor` field
    # check must fire first
    _approve_binding(other_profile, center)

    res = auth_client(doctor_user).post(
        "/api/doctors/schedules/",
        _schedule_payload(other_profile.id, center.id),
        format="json",
    )
    assert res.status_code == 400, res.data
    assert "themselves" in str(res.data).lower() or "own" in str(res.data).lower()
    assert DoctorSchedule.objects.count() == 0


def test_doctor_can_create_schedule_for_own_profile(
    auth_client, doctor_user
):
    profile = _make_doctor(doctor_user)
    center = _make_center("C-SCHED-OWN")
    _approve_binding(profile, center)

    res = auth_client(doctor_user).post(
        "/api/doctors/schedules/",
        _schedule_payload(profile.id, center.id),
        format="json",
    )
    assert res.status_code == 201, res.data
    assert DoctorSchedule.objects.count() == 1


# ---------- (b) schedules: center must be approved for the doctor ----------

def test_doctor_schedule_with_unapproved_center_returns_400(
    auth_client, doctor_user
):
    profile = _make_doctor(doctor_user)
    unapproved = _make_center("C-SCHED-UN-APPROVED")

    res = auth_client(doctor_user).post(
        "/api/doctors/schedules/",
        _schedule_payload(profile.id, unapproved.id),
        format="json",
    )
    assert res.status_code == 400
    assert "not approved" in str(res.data).lower()
    assert DoctorSchedule.objects.count() == 0


def test_doctor_schedule_with_approved_center_returns_201(auth_client, doctor_user):
    profile = _make_doctor(doctor_user)
    center = _make_center("C-SCHED-APPROVED2")
    _approve_binding(profile, center)

    res = auth_client(doctor_user).post(
        "/api/doctors/schedules/",
        _schedule_payload(profile.id, center.id),
        format="json",
    )
    assert res.status_code == 201, res.data
    assert DoctorSchedule.objects.count() == 1


# ---------- (c) scoped lists ----------

def test_doctor_schedule_list_scoped_to_own_profile(
    auth_client, doctor_user, make_user
):
    own_profile = _make_doctor(doctor_user)
    center = _make_center("C-SCHED-SCOPED")
    _approve_binding(own_profile, center)
    own_schedule = DoctorSchedule.objects.create(
        doctor=own_profile,
        center=center,
        weekday=0,
        start_time="09:00",
        end_time="17:00",
    )

    other_user = make_user("other_doc_sched2", "DOCTOR")
    other_profile = _make_doctor(other_user, "LIC-SCHED-OTHER2")
    other_center = _make_center("C-SCHED-OTHER")
    _approve_binding(other_profile, other_center)
    other_schedule = DoctorSchedule.objects.create(
        doctor=other_profile,
        center=other_center,
        weekday=1,
        start_time="08:00",
        end_time="16:00",
    )

    res = auth_client(doctor_user).get("/api/doctors/schedules/")
    assert res.status_code == 200
    ids = {item["id"] for item in res.data["results"]}
    assert own_schedule.id in ids
    assert other_schedule.id not in ids
