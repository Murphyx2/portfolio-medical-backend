from django.contrib.auth import get_user_model

from apps.accounts.models import User


def test_login_success(api_client, admin_user):
    res = api_client.post(
        "/api/auth/login/",
        {"username": "admin", "password": "pass12345"},
        format="json",
    )
    assert res.status_code == 200
    assert "access" in res.data and "refresh" not in res.data
    assert res.data["user"]["role"] == "ADMIN"


def test_login_failure(api_client, db):
    res = api_client.post(
        "/api/auth/login/",
        {"username": "nobody", "password": "wrong"},
        format="json",
    )
    assert res.status_code == 401


def test_login_wrong_password(api_client, admin_user):
    res = api_client.post(
        "/api/auth/login/",
        {"username": "admin", "password": "wrong"},
        format="json",
    )
    assert res.status_code == 401


def test_me_requires_auth(api_client):
    assert api_client.get("/api/auth/me/").status_code == 401


def test_me_returns_role(auth_client, admin_user):
    res = auth_client(admin_user).get("/api/auth/me/")
    assert res.status_code == 200
    assert res.data["role"] == "ADMIN"


def test_users_create_only_for_admin(auth_client, admin_user):
    client = auth_client(admin_user)
    res = client.post(
        "/api/auth/users/",
        {
            "username": "newdoc",
            "password": "pass12345",
            "first_name": "New",
            "last_name": "Doctor",
            "role": "DOCTOR",
        },
        format="json",
    )
    assert res.status_code == 201
    user = User.objects.get(username="newdoc")
    assert user.role == User.Role.DOCTOR
    assert user.check_password("pass12345")


def test_users_forbidden_for_doctor(auth_client, doctor_user):
    res = auth_client(doctor_user).get("/api/auth/users/")
    assert res.status_code in (401, 403)


def test_user_roles_endpoint(auth_client, admin_user):
    res = auth_client(admin_user).get("/api/auth/users/roles/")
    assert res.status_code == 200
    roles = {r["value"] for r in res.data}
    assert "ADMIN" in roles and "DOCTOR" in roles
