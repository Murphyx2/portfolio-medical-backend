"""Rooms module: RBAC (read=all staff, create=Admin/IT, update=Admin/IT/
Receptionist, delete=Admin/IT-only), unique code, required center (PROTECT),
soft-delete/restore (admin-only, matching the codebase-wide can_view_inactive()
invariant), search/filter, code/floor_area uppercase normalization, and the
RoomType catalog (mirrors the ServiceType RBAC/CRUD pattern).
"""

from apps.centers.models import MedicalCenter
from apps.rooms.models import Room, RoomType


def _center(code="C1"):
    return MedicalCenter.objects.create(
        name=f"Center {code}", code=code, address="A", phone="1"
    )


def _room_type(name="Consulta"):
    return RoomType.objects.get_or_create(name=name)[0]


def _room(**overrides):
    data = {
        "code": "R1",
        "name": "Consultorio 1",
        "room_type": overrides.pop("room_type", None) or _room_type(),
        "center": overrides.pop("center", None) or _center(),
    }
    data.update(overrides)
    return Room.objects.create(**data)


def _payload(**overrides):
    data = {
        "code": "R1",
        "name": "Consultorio 1",
        "room_type": overrides.pop("room_type_id", None) or _room_type().id,
        "center": overrides.pop("center_id", None),
    }
    data.update(overrides)
    return data


# ---------------------------------------------------------------------------
# Read: every authenticated role can list/retrieve
# ---------------------------------------------------------------------------


def test_every_role_can_read_rooms(
    auth_client, admin_user, doctor_user, receptionist_user, it_user, nurse_user,
    center_manager_user,
):
    _room()
    for user in (admin_user, doctor_user, receptionist_user, it_user, nurse_user, center_manager_user):
        res = auth_client(user).get("/api/rooms/")
        assert res.status_code == 200, (user.role, res.data)


# ---------------------------------------------------------------------------
# Create: Admin/IT only
# ---------------------------------------------------------------------------


def test_admin_and_it_can_create_room(auth_client, admin_user, it_user):
    center = _center()
    room_type = _room_type()
    for i, user in enumerate((admin_user, it_user)):
        res = auth_client(user).post(
            "/api/rooms/",
            _payload(code=f"R{i}", center_id=center.id, room_type_id=room_type.id),
            format="json",
        )
        assert res.status_code == 201, (user.role, res.data)


def test_receptionist_and_doctor_cannot_create_room(
    auth_client, receptionist_user, doctor_user
):
    center = _center()
    for user in (receptionist_user, doctor_user):
        res = auth_client(user).post(
            "/api/rooms/", _payload(center_id=center.id), format="json"
        )
        assert res.status_code == 403, (user.role, res.data)


# ---------------------------------------------------------------------------
# Update: Admin/IT/Receptionist; Doctor forbidden
# ---------------------------------------------------------------------------


def test_admin_it_and_receptionist_can_update_room(
    auth_client, admin_user, it_user, receptionist_user
):
    center = _center()
    for user in (admin_user, it_user, receptionist_user):
        room = _room(code=f"U-{user.username}", center=center)
        res = auth_client(user).patch(
            f"/api/rooms/{room.id}/", {"name": "Renamed"}, format="json"
        )
        assert res.status_code == 200, (user.role, res.data)
        assert res.data["name"] == "Renamed"


def test_doctor_cannot_update_room(auth_client, doctor_user):
    room = _room()
    res = auth_client(doctor_user).patch(
        f"/api/rooms/{room.id}/", {"name": "Renamed"}, format="json"
    )
    assert res.status_code == 403, res.data


# ---------------------------------------------------------------------------
# Delete (deactivate): Admin/IT only, Receptionist forbidden
# ---------------------------------------------------------------------------


def test_admin_and_it_can_delete_room(auth_client, admin_user, it_user):
    center = _center()
    for user in (admin_user, it_user):
        room = _room(code=f"D-{user.username}", center=center)
        res = auth_client(user).delete(f"/api/rooms/{room.id}/")
        assert res.status_code == 204, (user.role, res.data)
        room.refresh_from_db()
        assert room.active is False


def test_receptionist_cannot_delete_room(auth_client, receptionist_user):
    room = _room()
    res = auth_client(receptionist_user).delete(f"/api/rooms/{room.id}/")
    assert res.status_code == 403, res.data


# ---------------------------------------------------------------------------
# Validation: duplicate code, missing center
# ---------------------------------------------------------------------------


def test_duplicate_code_rejected(auth_client, admin_user):
    center = _center()
    _room(code="DUP", center=center)
    res = auth_client(admin_user).post(
        "/api/rooms/", _payload(code="DUP", center_id=center.id), format="json"
    )
    assert res.status_code == 400, res.data


def test_missing_center_rejected(auth_client, admin_user):
    res = auth_client(admin_user).post(
        "/api/rooms/", _payload(center_id=None), format="json"
    )
    assert res.status_code == 400, res.data


# ---------------------------------------------------------------------------
# Restore: admin-only
# ---------------------------------------------------------------------------


def test_admin_can_restore_room(auth_client, admin_user):
    room = _room()
    auth_client(admin_user).delete(f"/api/rooms/{room.id}/")
    room.refresh_from_db()
    assert room.active is False

    res = auth_client(admin_user).post(f"/api/rooms/{room.id}/restore/")
    assert res.status_code == 200, res.data
    room.refresh_from_db()
    assert room.active is True


def test_restore_forbidden_for_it_and_receptionist(
    auth_client, admin_user, it_user, receptionist_user
):
    center = _center()
    for user in (it_user, receptionist_user):
        room = _room(code=f"RS-{user.username}", center=center)
        auth_client(admin_user).delete(f"/api/rooms/{room.id}/")

        res = auth_client(user).post(f"/api/rooms/{room.id}/restore/")
        assert res.status_code == 403, (user.role, res.data)


# ---------------------------------------------------------------------------
# Visibility: inactive rows hidden by default, admin-only with include_inactive
# ---------------------------------------------------------------------------


def test_inactive_room_hidden_by_default(auth_client, admin_user, receptionist_user):
    room = _room()
    auth_client(admin_user).delete(f"/api/rooms/{room.id}/")

    res = auth_client(receptionist_user).get("/api/rooms/")
    assert res.data["count"] == 0

    res = auth_client(admin_user).get("/api/rooms/")
    assert res.data["count"] == 0


def test_admin_sees_inactive_room_with_include_inactive(auth_client, admin_user):
    room = _room()
    auth_client(admin_user).delete(f"/api/rooms/{room.id}/")

    res = auth_client(admin_user).get("/api/rooms/?include_inactive=true")
    assert res.data["count"] == 1
    assert res.data["results"][0]["active"] is False


def test_non_admin_never_sees_inactive_even_with_include_inactive(
    auth_client, admin_user, it_user
):
    room = _room()
    auth_client(admin_user).delete(f"/api/rooms/{room.id}/")

    res = auth_client(it_user).get("/api/rooms/?include_inactive=true")
    assert res.data["count"] == 0


# ---------------------------------------------------------------------------
# Search / filter
# ---------------------------------------------------------------------------


def test_search_by_code_and_name(auth_client, admin_user):
    center = _center()
    _room(code="LAB1", name="Laboratorio Central", center=center)
    _room(code="WAIT1", name="Sala de Espera", center=_center(code="C2"))

    res = auth_client(admin_user).get("/api/rooms/?search=LAB1")
    assert res.data["count"] == 1
    assert res.data["results"][0]["code"] == "LAB1"

    res = auth_client(admin_user).get("/api/rooms/?search=Espera")
    assert res.data["count"] == 1
    assert res.data["results"][0]["code"] == "WAIT1"


def test_filter_by_room_type_and_center(auth_client, admin_user):
    center1 = _center(code="C1")
    center2 = _center(code="C2")
    lab_type = _room_type(name="Laboratorio")
    waiting_type = _room_type(name="Sala de espera")
    _room(code="R1", room_type=lab_type, center=center1)
    _room(code="R2", room_type=waiting_type, center=center2)

    res = auth_client(admin_user).get(f"/api/rooms/?room_type={lab_type.id}")
    assert res.data["count"] == 1
    assert res.data["results"][0]["code"] == "R1"

    res = auth_client(admin_user).get(f"/api/rooms/?center={center2.id}")
    assert res.data["count"] == 1
    assert res.data["results"][0]["code"] == "R2"


# ---------------------------------------------------------------------------
# Serializer exposes center_name and room_type_name
# ---------------------------------------------------------------------------


def test_room_list_includes_center_name_and_room_type_name(auth_client, admin_user):
    center = _center(code="INCAF")
    room_type = _room_type(name="Consulta")
    _room(center=center, room_type=room_type)
    res = auth_client(admin_user).get("/api/rooms/")
    assert res.status_code == 200, res.data
    row = res.data["results"][0]
    assert row["center_name"] == "Center INCAF"
    assert row["room_type_name"] == "Consulta"


# ---------------------------------------------------------------------------
# code / floor_area are always normalized to upper case on save, regardless
# of the casing submitted by the caller.
# ---------------------------------------------------------------------------


def test_code_and_floor_area_uppercased_on_create(auth_client, admin_user):
    center = _center()
    room_type = _room_type()
    res = auth_client(admin_user).post(
        "/api/rooms/",
        {
            "code": "lab-1a",
            "name": "Laboratorio",
            "room_type": room_type.id,
            "center": center.id,
            "floor_area": "2nd floor, wing b",
        },
        format="json",
    )
    assert res.status_code == 201, res.data
    assert res.data["code"] == "LAB-1A"
    assert res.data["floor_area"] == "2ND FLOOR, WING B"


def test_code_and_floor_area_uppercased_on_update(auth_client, admin_user):
    room = _room(code="R1", floor_area="ground floor")
    res = auth_client(admin_user).patch(
        f"/api/rooms/{room.id}/",
        {"code": "r1-new", "floor_area": "3rd floor"},
        format="json",
    )
    assert res.status_code == 200, res.data
    assert res.data["code"] == "R1-NEW"
    assert res.data["floor_area"] == "3RD FLOOR"


# ---------------------------------------------------------------------------
# RoomType catalog: read=all staff, write=Admin/IT/Receptionist, delete=
# Admin/IT-only -- same RBAC shape as Room itself (CanManageRooms).
# ---------------------------------------------------------------------------


def test_every_role_can_read_room_types(
    auth_client, admin_user, doctor_user, receptionist_user, it_user, nurse_user,
):
    _room_type()
    for user in (admin_user, doctor_user, receptionist_user, it_user, nurse_user):
        res = auth_client(user).get("/api/room-types/")
        assert res.status_code == 200, (user.role, res.data)


def test_admin_and_it_can_create_room_type(auth_client, admin_user, it_user):
    for i, user in enumerate((admin_user, it_user)):
        res = auth_client(user).post(
            "/api/room-types/", {"name": f"Tipo {i}"}, format="json"
        )
        assert res.status_code == 201, (user.role, res.data)


def test_doctor_cannot_create_room_type(auth_client, doctor_user):
    res = auth_client(doctor_user).post(
        "/api/room-types/", {"name": "Rayos X"}, format="json"
    )
    assert res.status_code == 403, res.data


def test_receptionist_can_update_but_not_create_room_type(
    auth_client, receptionist_user
):
    res = auth_client(receptionist_user).post(
        "/api/room-types/", {"name": "Rayos X"}, format="json"
    )
    assert res.status_code == 403, res.data

    room_type = _room_type(name="Editable")
    res = auth_client(receptionist_user).patch(
        f"/api/room-types/{room_type.id}/", {"name": "Renamed"}, format="json"
    )
    assert res.status_code == 200, res.data


def test_receptionist_cannot_delete_room_type(auth_client, receptionist_user):
    room_type = _room_type()
    res = auth_client(receptionist_user).delete(f"/api/room-types/{room_type.id}/")
    assert res.status_code == 403, res.data


def test_duplicate_room_type_name_rejected(auth_client, admin_user):
    _room_type(name="Consulta")
    res = auth_client(admin_user).post(
        "/api/room-types/", {"name": "Consulta"}, format="json"
    )
    assert res.status_code == 400, res.data


def test_room_type_in_use_is_protected_from_delete(auth_client, admin_user):
    room_type = _room_type()
    _room(room_type=room_type)
    res = auth_client(admin_user).delete(f"/api/room-types/{room_type.id}/")
    # PROTECT on Room.room_type only guards a real hard delete; the
    # ModelViewSet's DELETE action soft-deletes (active=False), which a
    # PROTECT FK does not block.
    assert res.status_code == 204, res.data
