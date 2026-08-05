from apps.centers.models import DoctorCenterBinding, MedicalCenter
from apps.doctors.models import DoctorProfile


def _center_payload(**overrides):
    data = {
        "name": "Central Health",
        "code": "CH001",
        "address": "1 Hospital Rd",
        "phone": "555-0001",
    }
    data.update(overrides)
    return data


def _doctor_payload(**overrides):
    data = {
        "specialty": "Cardiology",
        "license_number": "LIC-100",
        "contact_phone": "555-0102",
    }
    data.update(overrides)
    return data


def _create_doctor_profile(user):
    return DoctorProfile.objects.create(
        user=user,
        specialty="Cardiology",
        license_number=f"LIC-{user.id}",
        contact_phone="555-0000",
    )


def test_admin_creates_center(auth_client, admin_user):
    res = auth_client(admin_user).post("/api/centers/", _center_payload(), format="json")
    assert res.status_code == 201
    assert MedicalCenter.objects.count() == 1


def test_receptionist_can_read_centers(auth_client, receptionist_user, admin_user):
    auth_client(admin_user).post("/api/centers/", _center_payload(), format="json")
    res = auth_client(receptionist_user).get("/api/centers/")
    assert res.status_code == 200
    assert res.data["count"] == 1


def test_receptionist_cannot_create_center(auth_client, receptionist_user):
    res = auth_client(receptionist_user).post("/api/centers/", _center_payload(), format="json")
    assert res.status_code in (401, 403)


def test_admin_creates_doctor_profile(auth_client, admin_user, doctor_user):
    res = auth_client(admin_user).post(
        "/api/doctors/profiles/",
        {**_doctor_payload(), "user": doctor_user.id},
        format="json",
    )
    assert res.status_code == 201
    assert DoctorProfile.objects.count() == 1


def test_doctor_sees_only_own_profile(auth_client, admin_user, doctor_user):
    p1 = _create_doctor_profile(doctor_user)
    auth_client(admin_user).post(
        "/api/doctors/profiles/",
        {**_doctor_payload(license_number="LIC-2"), "user": admin_user.id},
        format="json",
    )
    res = auth_client(doctor_user).get("/api/doctors/profiles/")
    assert res.status_code == 200
    ids = {item["id"] for item in res.data["results"]}
    assert ids == {p1.id}


def test_binding_requires_admin_to_approve(auth_client, admin_user, doctor_user):
    center = MedicalCenter.objects.create(
        name="C", code="C1", address="A", phone="1"
    )
    profile = _create_doctor_profile(doctor_user)
    res = auth_client(admin_user).post(
        "/api/bindings/",
        {"doctor": profile.id, "center": center.id},
        format="json",
    )
    assert res.status_code == 201
    binding = DoctorCenterBinding.objects.get()
    assert binding.approved is True
    assert binding.approved_by == admin_user
