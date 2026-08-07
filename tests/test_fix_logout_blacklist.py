"""H-03: refresh tokens live in an httpOnly cookie, never in the login body.

- Login sets an httpOnly SameSite=Strict mc_refresh cookie (scoped to
  /api/auth/) and returns only {access, user} — no refresh in the body.
- POST /api/auth/token/refresh/ reads the cookie, rotates it (the old refresh
  is blacklisted), and sets a fresh cookie; the body carries only a new access.
- POST /api/auth/logout/ blacklists the cookie's refresh and clears the cookie.
"""

from django.conf import settings


def _login(client, username, password):
    return client.post(
        "/api/auth/login/",
        {"username": username, "password": password},
        format="json",
    )


def test_login_returns_access_only_and_sets_http_only_cookie(api_client, admin_user):
    login = _login(api_client, admin_user.username, "pass12345")
    assert login.status_code == 200, login.data
    assert "access" in login.data
    assert "refresh" not in login.data

    cookie = login.cookies[settings.REFRESH_COOKIE_NAME]
    assert cookie.value
    assert str(cookie["httponly"]) == "True"
    assert str(cookie["samesite"]) == "Strict"
    assert str(cookie["path"]) == settings.REFRESH_COOKIE_PATH
    assert str(cookie.get("secure")) == (
        "True" if settings.REFRESH_COOKIE_SECURE else ""
    )


def test_refresh_reads_cookie_rotates_and_blacklists_old(api_client, admin_user):
    login = _login(api_client, admin_user.username, "pass12345")
    assert login.status_code == 200
    old_refresh = login.cookies[settings.REFRESH_COOKIE_NAME].value

    rotated = api_client.post("/api/auth/token/refresh/", {}, format="json")
    assert rotated.status_code == 200
    assert "access" in rotated.data
    assert "refresh" not in rotated.data
    new_refresh = rotated.cookies[settings.REFRESH_COOKIE_NAME].value
    assert new_refresh and new_refresh != old_refresh

    # Replaying the rotated-away refresh must be rejected (401 blacklisted).
    api_client.cookies[settings.REFRESH_COOKIE_NAME] = old_refresh
    reuse = api_client.post("/api/auth/token/refresh/", {}, format="json")
    assert reuse.status_code == 401


def test_refresh_without_cookie_returns_401(api_client):
    res = api_client.post("/api/auth/token/refresh/", {}, format="json")
    assert res.status_code == 401


def test_logout_blacklists_cookie_refresh_and_clears_cookie(api_client, admin_user):
    login = _login(api_client, admin_user.username, "pass12345")
    assert login.status_code == 200
    access = login.data["access"]
    refresh = login.cookies[settings.REFRESH_COOKIE_NAME].value

    res = api_client.post(
        "/api/auth/logout/",
        {},
        HTTP_AUTHORIZATION=f"Bearer {access}",
        format="json",
    )
    assert res.status_code == 204
    cleared = res.cookies[settings.REFRESH_COOKIE_NAME]
    assert cleared.value == ""

    # The logout'd refresh must no longer be usable to mint tokens.
    api_client.cookies[settings.REFRESH_COOKIE_NAME] = refresh
    reuse = api_client.post("/api/auth/token/refresh/", {}, format="json")
    assert reuse.status_code == 401
    assert reuse.data.get("code") == "token_not_valid"


def test_logout_without_cookie_returns_400(api_client, admin_user):
    login = _login(api_client, admin_user.username, "pass12345")
    del api_client.cookies[settings.REFRESH_COOKIE_NAME]
    res = api_client.post(
        "/api/auth/logout/",
        {},
        HTTP_AUTHORIZATION=f"Bearer {login.data['access']}",
        format="json",
    )
    assert res.status_code == 400


def test_logout_requires_authentication(api_client):
    res = api_client.post("/api/auth/logout/", {}, format="json")
    assert res.status_code in (400, 401)
