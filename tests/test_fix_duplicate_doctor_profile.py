"""Fix P1: POST /api/doctors/profiles/ with a user that already has a
DoctorProfile must return HTTP 400 (previously a 500 via IntegrityError)."""

from apps.doctors.models import DoctorProfile


def _profile_payload(user_id, **overrides):
    data = {
        "user": user_id,
        "specialty": "Cardiology",
        "license_number": "LIC-DUP-1",
        "contact_phone": "555-0102",
    }
    data.update(overrides)
    return data


def test_duplicate_doctor_profile_returns_400(auth_client, admin_user, doctor_user):
    client = auth_client(admin_user)

    first = client.post(
        "/api/doctors/profiles/",
        _profile_payload(doctor_user.id),
        format="json",
    )
    assert first.status_code == 201
    assert DoctorProfile.objects.count() == 1

    duplicate = client.post(
        "/api/doctors/profiles/",
        _profile_payload(doctor_user.id, license_number="LIC-DUP-2"),
        format="json",
    )
    assert duplicate.status_code == 400, duplicate.data
    # must not create a second profile row
    assert DoctorProfile.objects.count() == 1
    detail = str(duplicate.data)
    assert "already has a doctor profile" in detail


def test_duplicate_profile_via_serializer_validation(auth_client, admin_user, doctor_user):
    """Regression: the serializer-level validation path also rejects duplicates
    (not only the view-level IntegrityError handler)."""
    client = auth_client(admin_user)
    first = client.post(
        "/api/doctors/profiles/",
        _profile_payload(doctor_user.id),
        format="json",
    )
    assert first.status_code == 201

    dup = client.post(
        "/api/doctors/profiles/",
        _profile_payload(doctor_user.id, license_number="LIC-DUP-3"),
        format="json",
    )
    assert dup.status_code == 400
    assert "already has a doctor profile" in str(dup.data)


def test_distinct_users_may_each_have_a_profile(auth_client, admin_user, doctor_user, make_user):
    """Different users can each have their own profile (uniqueness is per user)."""
    second_doctor = make_user("second_doctor", "DOCTOR")
    client = auth_client(admin_user)

    first = client.post(
        "/api/doctors/profiles/",
        _profile_payload(doctor_user.id, license_number="LIC-A"),
        format="json",
    )
    second = client.post(
        "/api/doctors/profiles/",
        _profile_payload(second_doctor.id, license_number="LIC-B"),
        format="json",
    )
    assert first.status_code == 201
    assert second.status_code == 201
    assert DoctorProfile.objects.count() == 2
