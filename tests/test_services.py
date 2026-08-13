"""Services module: RBAC (read=all staff, write=ADMIN/CENTER_MANAGER),
soft-delete/restore, non-unique SIMON, and ServiceType lookup behavior."""

from apps.services.models import Service, ServiceType


def _service_type(name="Consult"):
    return ServiceType.objects.create(name=name)


def _service(**overrides):
    data = {
        "simon": "123456",
        "name": "Consulta general",
        "type": overrides.pop("type", None) or _service_type(),
        "co_pago": "500.00",
        "privado": "1500.00",
    }
    data.update(overrides)
    return Service.objects.create(**data)


# ---------------------------------------------------------------------------
# Read: every authenticated role can list/retrieve
# ---------------------------------------------------------------------------


def test_every_role_can_read_services(
    auth_client, admin_user, doctor_user, receptionist_user, it_user, nurse_user,
    center_manager_user,
):
    _service()
    for user in (admin_user, doctor_user, receptionist_user, it_user, nurse_user, center_manager_user):
        res = auth_client(user).get("/api/services/")
        assert res.status_code == 200, (user.role, res.data)
        res = auth_client(user).get("/api/service-types/")
        assert res.status_code == 200, (user.role, res.data)


# ---------------------------------------------------------------------------
# Write: only ADMIN and CENTER_MANAGER
# ---------------------------------------------------------------------------


def test_admin_and_center_manager_can_create_service(
    auth_client, admin_user, center_manager_user
):
    st = _service_type()
    for user in (admin_user, center_manager_user):
        res = auth_client(user).post(
            "/api/services/",
            {
                "simon": "111222",
                "name": f"Servicio {user.username}",
                "type": st.id,
                "co_pago": "100.00",
                "privado": "300.00",
            },
            format="json",
        )
        assert res.status_code == 201, (user.role, res.data)


def test_other_roles_cannot_write_services(
    auth_client, doctor_user, receptionist_user, it_user, nurse_user
):
    st = _service_type()
    svc = _service(type=st)
    for user in (doctor_user, receptionist_user, it_user, nurse_user):
        res = auth_client(user).post(
            "/api/services/",
            {"simon": "999999", "name": "X", "type": st.id, "co_pago": "1", "privado": "1"},
            format="json",
        )
        assert res.status_code == 403, (user.role, res.data)

        res = auth_client(user).patch(
            f"/api/services/{svc.id}/", {"name": "Renamed"}, format="json"
        )
        assert res.status_code == 403, (user.role, res.data)

        res = auth_client(user).delete(f"/api/services/{svc.id}/")
        assert res.status_code == 403, (user.role, res.data)


def test_center_manager_can_deactivate_service(auth_client, center_manager_user):
    svc = _service()
    res = auth_client(center_manager_user).delete(f"/api/services/{svc.id}/")
    assert res.status_code == 204, res.data
    svc.refresh_from_db()
    assert svc.active is False


def test_other_roles_cannot_write_service_types(auth_client, doctor_user):
    res = auth_client(doctor_user).post(
        "/api/service-types/", {"name": "Lab Work"}, format="json"
    )
    assert res.status_code == 403, res.data


def test_admin_and_center_manager_can_create_service_type(
    auth_client, admin_user, center_manager_user
):
    res = auth_client(admin_user).post(
        "/api/service-types/", {"name": "Lab Work"}, format="json"
    )
    assert res.status_code == 201, res.data

    res = auth_client(center_manager_user).post(
        "/api/service-types/", {"name": "Imaging"}, format="json"
    )
    assert res.status_code == 201, res.data


# ---------------------------------------------------------------------------
# SIMON is intentionally not unique
# ---------------------------------------------------------------------------


def test_duplicate_simon_allowed_across_services(auth_client, admin_user):
    st = _service_type()
    body = lambda name: {  # noqa: E731
        "simon": "004521",
        "name": name,
        "type": st.id,
        "co_pago": "200.00",
        "privado": "600.00",
    }
    res1 = auth_client(admin_user).post("/api/services/", body("Consulta psicología infantil"), format="json")
    res2 = auth_client(admin_user).post("/api/services/", body("Consulta psicología adultos"), format="json")
    assert res1.status_code == 201, res1.data
    assert res2.status_code == 201, res2.data
    assert res1.data["simon"] == res2.data["simon"] == "004521"


# ---------------------------------------------------------------------------
# Soft-delete + restore (admin only, matching the codebase-wide
# can_view_inactive() invariant -- restore is never opened to non-admins)
# ---------------------------------------------------------------------------


def test_admin_can_restore_service(auth_client, admin_user):
    svc = _service()
    auth_client(admin_user).delete(f"/api/services/{svc.id}/")
    svc.refresh_from_db()
    assert svc.active is False

    res = auth_client(admin_user).post(f"/api/services/{svc.id}/restore/")
    assert res.status_code == 200, res.data
    svc.refresh_from_db()
    assert svc.active is True


def test_restore_forbidden_for_non_admin(auth_client, admin_user, receptionist_user):
    svc = _service()
    auth_client(admin_user).delete(f"/api/services/{svc.id}/")

    res = auth_client(receptionist_user).post(f"/api/services/{svc.id}/restore/")
    assert res.status_code == 403, res.data


# ---------------------------------------------------------------------------
# type_name convenience field + PROTECT-safe soft delete of ServiceType
# ---------------------------------------------------------------------------


def test_service_list_includes_type_name(auth_client, admin_user):
    st = _service_type("Physical Therapy")
    _service(type=st)
    res = auth_client(admin_user).get("/api/services/")
    assert res.status_code == 200, res.data
    assert res.data["results"][0]["type_name"] == "Physical Therapy"


def test_deactivating_service_type_does_not_break_existing_services(
    auth_client, admin_user
):
    st = _service_type("Dermatology")
    svc = _service(type=st)

    res = auth_client(admin_user).delete(f"/api/service-types/{st.id}/")
    assert res.status_code == 204, res.data

    svc.refresh_from_db()
    assert svc.active is True
    assert svc.type_id == st.id

    res = auth_client(admin_user).get(f"/api/services/{svc.id}/")
    assert res.status_code == 200, res.data
    assert res.data["type_name"] == "Dermatology"


def test_seed_migration_created_default_service_types(db):
    names = set(ServiceType.objects.values_list("name", flat=True))
    assert {"Admission", "Vaccination", "Emergency"}.issubset(names)
