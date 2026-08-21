from apps.centers.models import DoctorCenterBinding, MedicalCenter
from apps.doctors.models import DoctorProfile
from apps.rooms.models import Room, RoomType
from apps.services.models import Service, ServiceType


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
        "license_number": "LIC-100",
        "contact_phone": "8095550102",
    }
    data.update(overrides)
    return data


def _create_doctor_profile(user):
    return DoctorProfile.objects.create(
        user=user,
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


def test_doctor_default_room_prefills_and_reports_name(auth_client, admin_user, doctor_user):
    from apps.rooms.models import Room, RoomType

    center = MedicalCenter.objects.create(name="C", code="C1", address="A", phone="1")
    room_type = RoomType.objects.get_or_create(name="Consulta")[0]
    room = Room.objects.create(code="R1", name="Room 1", room_type=room_type, center=center)
    profile = _create_doctor_profile(doctor_user)

    res = auth_client(admin_user).patch(
        f"/api/doctors/profiles/{profile.id}/", {"default_room": room.id}, format="json"
    )
    assert res.status_code == 200, res.data
    assert res.data["default_room"] == room.id
    assert res.data["default_room_name"] == "Room 1"


def test_doctor_code_auto_generated_and_unique(make_user):
    from apps.accounts.models import User

    u1 = make_user("doc-code-1", User.Role.DOCTOR)
    u2 = make_user("doc-code-2", User.Role.DOCTOR)
    p1 = _create_doctor_profile(u1)
    p2 = _create_doctor_profile(u2)

    assert p1.code == f"DR{p1.id:04d}"
    assert p2.code == f"DR{p2.id:04d}"
    assert p1.code != p2.code


def test_doctor_code_uppercased_when_provided(make_user):
    from apps.accounts.models import User

    user = make_user("doc-code-3", User.Role.DOCTOR)
    profile = DoctorProfile.objects.create(
        user=user,
        license_number="LIC-code-3",
        contact_phone="8095550000",
        code="dr-custom",
    )
    assert profile.code == "DR-CUSTOM"


def test_doctor_code_stays_visible_even_when_license_number_is_masked(
    auth_client, doctor_user, nurse_user
):
    profile = _create_doctor_profile(doctor_user)
    res = auth_client(nurse_user).get(f"/api/doctors/profiles/{profile.id}/")
    assert res.status_code == 200, res.data
    # license_number is masked for non-admin/IT/self roles (M-03); code is
    # explicitly non-PII and must stay legible regardless.
    assert res.data["license_number"] != profile.license_number
    assert res.data["code"] == profile.code


def _service(name="Consulta General", **overrides):
    service_type = ServiceType.objects.create(name=f"Type-{name}")
    data = {
        "simon": "1",
        "name": name,
        "type": service_type,
        "co_pago": "0",
        "privado": "0",
    }
    data.update(overrides)
    return Service.objects.create(**data)


def test_admin_can_set_doctor_services(auth_client, admin_user, doctor_user):
    profile = _create_doctor_profile(doctor_user)
    s1, s2 = _service("Consulta General"), _service("Radiografia")
    res = auth_client(admin_user).patch(
        f"/api/doctors/profiles/{profile.id}/",
        {"services": [s1.id, s2.id]},
        format="json",
    )
    assert res.status_code == 200, res.data
    profile.refresh_from_db()
    assert set(profile.services.values_list("id", flat=True)) == {s1.id, s2.id}
    assert {s["id"] for s in res.data["services_detail"]} == {s1.id, s2.id}


def test_center_manager_can_set_doctor_services(auth_client, center_manager_user, doctor_user):
    profile = _create_doctor_profile(doctor_user)
    service = _service()
    res = auth_client(center_manager_user).patch(
        f"/api/doctors/profiles/{profile.id}/",
        {"services": [service.id]},
        format="json",
    )
    assert res.status_code == 200, res.data
    profile.refresh_from_db()
    assert list(profile.services.values_list("id", flat=True)) == [service.id]


def test_it_cannot_set_doctor_services(auth_client, it_user, admin_user, doctor_user):
    profile = _create_doctor_profile(doctor_user)
    service = _service()
    res = auth_client(it_user).patch(
        f"/api/doctors/profiles/{profile.id}/",
        {"services": [service.id]},
        format="json",
    )
    assert res.status_code == 400, res.data
    profile.refresh_from_db()
    assert profile.services.count() == 0


def test_doctor_cannot_set_own_services(auth_client, doctor_user):
    profile = _create_doctor_profile(doctor_user)
    service = _service()
    res = auth_client(doctor_user).patch(
        f"/api/doctors/profiles/{profile.id}/",
        {"services": [service.id]},
        format="json",
    )
    # DOCTOR isn't in IsAdminOrITOrCenterManager at all, so this is blocked
    # at the view-permission layer, not the serializer's field validator.
    assert res.status_code == 403, res.data


def test_any_staff_role_can_read_doctor_services(auth_client, admin_user, it_user, doctor_user):
    profile = _create_doctor_profile(doctor_user)
    service = _service()
    profile.services.add(service)
    res = auth_client(it_user).get(f"/api/doctors/profiles/{profile.id}/")
    assert res.status_code == 200, res.data
    assert res.data["services_detail"] == [{"id": service.id, "name": service.name}]


def test_center_manager_cannot_edit_other_doctor_fields(auth_client, center_manager_user, doctor_user):
    profile = _create_doctor_profile(doctor_user)
    service = _service()
    res = auth_client(center_manager_user).patch(
        f"/api/doctors/profiles/{profile.id}/",
        {"services": [service.id], "license_number": "LIC-HIJACK"},
        format="json",
    )
    assert res.status_code == 400, res.data
    profile.refresh_from_db()
    assert profile.license_number != "LIC-HIJACK"


def test_doctor_services_write_excludes_inactive_service(auth_client, admin_user, doctor_user):
    profile = _create_doctor_profile(doctor_user)
    inactive = _service("Old Service", active=False)
    res = auth_client(admin_user).patch(
        f"/api/doctors/profiles/{profile.id}/",
        {"services": [inactive.id]},
        format="json",
    )
    assert res.status_code == 400, res.data


def _room(name="Room 1", **overrides):
    code = name.upper().replace(" ", "-")
    center = overrides.pop("center", None) or MedicalCenter.objects.create(
        **_center_payload(code=f"C-{code}")
    )
    room_type = RoomType.objects.create(name=f"Type-{name}")
    data = {
        "code": code,
        "name": name,
        "room_type": room_type,
        "center": center,
    }
    data.update(overrides)
    return Room.objects.create(**data)


def test_admin_can_set_doctor_rooms(auth_client, admin_user, doctor_user):
    profile = _create_doctor_profile(doctor_user)
    r1, r2 = _room("Room A"), _room("Room B")
    res = auth_client(admin_user).patch(
        f"/api/doctors/profiles/{profile.id}/",
        {"rooms": [r1.id, r2.id]},
        format="json",
    )
    assert res.status_code == 200, res.data
    profile.refresh_from_db()
    assert set(profile.rooms.values_list("id", flat=True)) == {r1.id, r2.id}
    assert {r["id"] for r in res.data["rooms_detail"]} == {r1.id, r2.id}


def test_center_manager_can_set_doctor_rooms(auth_client, center_manager_user, doctor_user):
    profile = _create_doctor_profile(doctor_user)
    room = _room()
    res = auth_client(center_manager_user).patch(
        f"/api/doctors/profiles/{profile.id}/",
        {"rooms": [room.id]},
        format="json",
    )
    assert res.status_code == 200, res.data
    profile.refresh_from_db()
    assert list(profile.rooms.values_list("id", flat=True)) == [room.id]


def test_it_cannot_set_doctor_rooms(auth_client, it_user, admin_user, doctor_user):
    profile = _create_doctor_profile(doctor_user)
    room = _room()
    res = auth_client(it_user).patch(
        f"/api/doctors/profiles/{profile.id}/",
        {"rooms": [room.id]},
        format="json",
    )
    assert res.status_code == 400, res.data
    profile.refresh_from_db()
    assert profile.rooms.count() == 0


def test_any_staff_role_can_read_doctor_rooms(auth_client, admin_user, it_user, doctor_user):
    profile = _create_doctor_profile(doctor_user)
    room = _room()
    profile.rooms.add(room)
    res = auth_client(it_user).get(f"/api/doctors/profiles/{profile.id}/")
    assert res.status_code == 200, res.data
    assert res.data["rooms_detail"] == [{"id": room.id, "name": room.name}]


def test_center_manager_cannot_edit_other_doctor_fields_via_rooms(auth_client, center_manager_user, doctor_user):
    profile = _create_doctor_profile(doctor_user)
    room = _room()
    res = auth_client(center_manager_user).patch(
        f"/api/doctors/profiles/{profile.id}/",
        {"rooms": [room.id], "license_number": "LIC-HIJACK"},
        format="json",
    )
    assert res.status_code == 400, res.data
    profile.refresh_from_db()
    assert profile.license_number != "LIC-HIJACK"
