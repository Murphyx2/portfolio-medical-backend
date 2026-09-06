from datetime import timedelta

from django.contrib.auth import get_user_model
from django.utils import timezone

from apps.accounts.models import User
from apps.core.models import AuditLog


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
            "doctor_profile": {"mode": "create"},
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


def test_lockout_after_five_failed_logins(api_client, doctor_user):
    for _ in range(5):
        res = api_client.post(
            "/api/auth/login/",
            {"username": "doctor", "password": "wrong"},
            format="json",
        )
        assert res.status_code == 401
    doctor_user.refresh_from_db()
    assert doctor_user.is_locked

    # Correct password still fails while locked.
    res = api_client.post(
        "/api/auth/login/",
        {"username": "doctor", "password": "pass12345"},
        format="json",
    )
    assert res.status_code == 423


def test_successful_login_resets_failed_count(api_client, doctor_user):
    api_client.post(
        "/api/auth/login/", {"username": "doctor", "password": "wrong"}, format="json"
    )
    res = api_client.post(
        "/api/auth/login/",
        {"username": "doctor", "password": "pass12345"},
        format="json",
    )
    assert res.status_code == 200
    doctor_user.refresh_from_db()
    assert doctor_user.failed_login_count == 0
    assert doctor_user.locked_until is None


def test_admin_can_unlock_locked_account(auth_client, admin_user, doctor_user):
    doctor_user.failed_login_count = 5
    doctor_user.locked_until = timezone.now() + timedelta(minutes=30)
    doctor_user.save()

    res = auth_client(admin_user).post(f"/api/auth/users/{doctor_user.id}/unlock/")
    assert res.status_code == 200
    doctor_user.refresh_from_db()
    assert not doctor_user.is_locked
    assert doctor_user.failed_login_count == 0


def test_it_cannot_unlock_account(auth_client, it_user, doctor_user):
    doctor_user.locked_until = timezone.now() + timedelta(minutes=30)
    doctor_user.save()
    res = auth_client(it_user).post(f"/api/auth/users/{doctor_user.id}/unlock/")
    assert res.status_code == 403


def test_admin_can_reset_password(auth_client, admin_user, doctor_user, api_client):
    res = auth_client(admin_user).post(
        f"/api/auth/users/{doctor_user.id}/set_password/",
        {"password": "newpass456"},
        format="json",
    )
    assert res.status_code == 204
    login = api_client.post(
        "/api/auth/login/",
        {"username": "doctor", "password": "newpass456"},
        format="json",
    )
    assert login.status_code == 200


def test_it_cannot_reset_password(auth_client, it_user, doctor_user):
    res = auth_client(it_user).post(
        f"/api/auth/users/{doctor_user.id}/set_password/",
        {"password": "newpass456"},
        format="json",
    )
    assert res.status_code == 403


def test_admin_can_view_user_activity(api_client, auth_client, admin_user, doctor_user):
    # Generates a FAILED_LOGIN audit row attributed to doctor_user (the actor).
    api_client.post(
        "/api/auth/login/", {"username": "doctor", "password": "wrong"}, format="json"
    )
    res = auth_client(admin_user).get(f"/api/auth/users/{doctor_user.id}/activity/")
    assert res.status_code == 200
    assert res.data["count"] >= 1
    assert res.data["results"][0]["action"] == "FAILED_LOGIN"


def test_it_cannot_view_user_activity(auth_client, it_user, doctor_user):
    res = auth_client(it_user).get(f"/api/auth/users/{doctor_user.id}/activity/")
    assert res.status_code == 403


def test_it_cannot_deactivate_or_restore_user(auth_client, it_user, doctor_user):
    client = auth_client(it_user)
    assert client.delete(f"/api/auth/users/{doctor_user.id}/").status_code == 403
    assert client.post(f"/api/auth/users/{doctor_user.id}/restore/").status_code in (403, 404)


def test_update_audit_log_records_changed_fields(auth_client, admin_user, doctor_user):
    res = auth_client(admin_user).patch(
        f"/api/auth/users/{doctor_user.id}/",
        {"role": "NURSE"},
        format="json",
    )
    assert res.status_code == 200
    entry = AuditLog.objects.filter(
        action="UPDATE", target_type="User", target_id=doctor_user.id
    ).latest("created_at")
    assert entry.details == {"changed_fields": ["role"]}
    assert entry.target_type == "User"
    assert entry.target_id == doctor_user.id


def test_update_audit_log_diffs_full_form_submission(auth_client, admin_user, doctor_user):
    # The frontend PATCHes every field on every edit, not just the one the
    # user touched -- changed_fields must reflect actual value changes, not
    # just which keys were present in the request body.
    res = auth_client(admin_user).patch(
        f"/api/auth/users/{doctor_user.id}/",
        {
            "username": doctor_user.username,
            "email": doctor_user.email,
            "first_name": doctor_user.first_name,
            "last_name": doctor_user.last_name,
            "role": "NURSE",
        },
        format="json",
    )
    assert res.status_code == 200
    entry = AuditLog.objects.filter(
        action="UPDATE", target_type="User", target_id=doctor_user.id
    ).latest("created_at")
    assert entry.details == {"changed_fields": ["role"]}
