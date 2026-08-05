"""Fix H-02: POST /api/auth/logout/ blacklists the refresh token.

- Logout with a valid refresh + bearer access -> 204 and the refresh can no
  longer be used at /api/auth/token/refresh/ (401 blacklisted).
- Logout with a missing refresh -> 400.
- JWT refresh rotation regression: using a refresh rotates it (old becomes
  invalid), matching ROTATE_REFRESH_TOKENS + BLACKLIST_AFTER_ROTATION.
"""

from rest_framework_simplejwt.tokens import RefreshToken


def _login(client, username, password):
    return client.post(
        "/api/auth/login/",
        {"username": username, "password": password},
        format="json",
    )


def test_logout_returns_204_and_blacklists_refresh(api_client, admin_user):
    # Real JWT flow: login issues access + refresh (throttle applies to the
    # view but a single login is well under the 10/min limit).
    login = _login(api_client, admin_user.username, "pass12345")
    assert login.status_code == 200, login.data
    access = login.data["access"]
    refresh = login.data["refresh"]

    res = api_client.post(
        "/api/auth/logout/",
        {"refresh": refresh},
        HTTP_AUTHORIZATION=f"Bearer {access}",
        format="json",
    )
    assert res.status_code == 204

    reuse = api_client.post(
        "/api/auth/token/refresh/",
        {"refresh": refresh},
        format="json",
    )
    assert reuse.status_code == 401
    # Language-agnostic: SimpleJWT returns {"detail": ..., "code": "token_not_valid"}
    # for blacklisted tokens (detail text is localized, e.g. Spanish under LANGUAGE_CODE="es").
    assert reuse.data.get("code") == "token_not_valid"


def test_logout_missing_refresh_returns_400(api_client, admin_user):
    login = _login(api_client, admin_user.username, "pass12345")
    assert login.status_code == 200
    res = api_client.post(
        "/api/auth/logout/",
        {},
        HTTP_AUTHORIZATION=f"Bearer {login.data['access']}",
        format="json",
    )
    assert res.status_code == 400


def test_logout_requires_authentication(api_client):
    res = api_client.post("/api/auth/logout/", {"refresh": "garbage"}, format="json")
    # Anonymous: must not be allowed to blacklist tokens.
    assert res.status_code in (400, 401)


def test_refresh_rotation_blacklists_old_token(api_client, admin_user):
    """Regression (item 6): refresh use rotates the token family; the old
    refresh must be blacklisted after rotation."""
    login = _login(api_client, admin_user.username, "pass12345")
    assert login.status_code == 200
    old_refresh = login.data["refresh"]

    rotated = api_client.post(
        "/api/auth/token/refresh/",
        {"refresh": old_refresh},
        format="json",
    )
    assert rotated.status_code == 200
    assert "access" in rotated.data and "refresh" in rotated.data

    reuse_old = api_client.post(
        "/api/auth/token/refresh/",
        {"refresh": old_refresh},
        format="json",
    )
    assert reuse_old.status_code == 401
