from apps.centers.models import DoctorCenterBinding, MedicalCenter
from apps.doctors.models import DoctorProfile


def _center_payload(**overrides):
    data = {
        "name": "Central Health",
        "code": "CH001",
        "address": "1 Hospital Rd",
        "phone": "8095550001",
    }
    data.update(overrides)
    return data


def _doctor_payload(**overrides):
    data = {
        "specialty": "Cardiology",
        "license_number": "LIC-100",
        "contact_phone": "8095550102",
    }
    data.update(overrides)
    return data


def _create_doctor_profile(user):
    return DoctorProfile.objects.create(
        user=user,
        specialty="Cardiology",
        license_number=f"LIC-{user.id}",
        contact_phone="8095550000",
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


def test_center_is_default_false_by_default(auth_client, admin_user):
    res = auth_client(admin_user).post("/api/centers/", _center_payload(), format="json")
    assert res.status_code == 201, res.data
    assert res.data["is_default"] is False


def test_setting_center_default_unsets_previous_default(auth_client, admin_user):
    first = auth_client(admin_user).post(
        "/api/centers/", _center_payload(is_default=True), format="json"
    )
    assert first.status_code == 201, first.data
    assert first.data["is_default"] is True

    second = auth_client(admin_user).post(
        "/api/centers/",
        _center_payload(code="CH002", is_default=True),
        format="json",
    )
    assert second.status_code == 201, second.data
    assert second.data["is_default"] is True

    first_center = MedicalCenter.objects.get(pk=first.data["id"])
    assert first_center.is_default is False
    assert MedicalCenter.objects.filter(is_default=True).count() == 1


def test_patch_center_default_unsets_previous_default(auth_client, admin_user):
    first = auth_client(admin_user).post(
        "/api/centers/", _center_payload(is_default=True), format="json"
    )
    second = auth_client(admin_user).post(
        "/api/centers/", _center_payload(code="CH003"), format="json"
    )
    assert second.data["is_default"] is False

    patched = auth_client(admin_user).patch(
        f"/api/centers/{second.data['id']}/", {"is_default": True}, format="json"
    )
    assert patched.status_code == 200, patched.data

    first_center = MedicalCenter.objects.get(pk=first.data["id"])
    assert first_center.is_default is False
    assert MedicalCenter.objects.filter(is_default=True).count() == 1


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
