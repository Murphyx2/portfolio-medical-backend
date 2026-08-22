"""Tests for the runtime-editable operational-settings feature
(apps/systemsettings): RBAC matrix, range validation, cache invalidation,
reset-to-defaults, and per-setting runtime enforcement across the rewired
consumers (lockout, throttles, JWT lifetimes, password policy, upload size,
media-token TTL, pagination default)."""

import io

import pytest
from django.core.cache import cache
from PIL import Image
from rest_framework_simplejwt.tokens import UntypedToken

from apps.core.models import AuditLog
from apps.patients.models import Patient
from apps.records.models import MedicalRecord
from apps.systemsettings.models import SystemSettings
from apps.systemsettings.services import CACHE_KEY, get_settings, invalidate_settings_cache

pytestmark = pytest.mark.django_db


# ---------------------------------------------------------------------------
# RBAC matrix
# ---------------------------------------------------------------------------


def test_unauthenticated_is_rejected(api_client):
    assert api_client.get("/api/settings/").status_code == 401
    assert api_client.patch("/api/settings/", {}, format="json").status_code == 401


def test_admin_can_read_and_write(auth_client, admin_user):
    client = auth_client(admin_user)
    res = client.get("/api/settings/")
    assert res.status_code == 200
    assert res.data["login_lockout_threshold"] == 5

    res = client.patch(
        "/api/settings/", {"login_lockout_threshold": 7}, format="json"
    )
    assert res.status_code == 200
    assert res.data["login_lockout_threshold"] == 7


def test_it_can_read_but_not_write(auth_client, it_user):
    client = auth_client(it_user)
    assert client.get("/api/settings/").status_code == 200
    res = client.patch(
        "/api/settings/", {"login_lockout_threshold": 7}, format="json"
    )
    assert res.status_code == 403


@pytest.mark.parametrize(
    "role_fixture",
    ["doctor_user", "nurse_user", "receptionist_user", "center_manager_user"],
)
def test_other_roles_are_denied(auth_client, role_fixture, request):
    user = request.getfixturevalue(role_fixture)
    client = auth_client(user)
    assert client.get("/api/settings/").status_code == 403
    assert client.patch("/api/settings/", {}, format="json").status_code == 403


# ---------------------------------------------------------------------------
# Range validation
# ---------------------------------------------------------------------------


def test_patch_rejects_out_of_range_value(auth_client, admin_user):
    client = auth_client(admin_user)
    res = client.patch(
        "/api/settings/", {"access_token_lifetime_minutes": 61}, format="json"
    )
    assert res.status_code == 400
    assert "access_token_lifetime_minutes" in res.data


def test_patch_rejects_below_minimum(auth_client, admin_user):
    client = auth_client(admin_user)
    res = client.patch(
        "/api/settings/", {"login_lockout_threshold": 0}, format="json"
    )
    assert res.status_code == 400
    assert "login_lockout_threshold" in res.data


def test_patch_accepts_boundary_values(auth_client, admin_user):
    client = auth_client(admin_user)
    res = client.patch(
        "/api/settings/", {"access_token_lifetime_minutes": 60}, format="json"
    )
    assert res.status_code == 200
    assert res.data["access_token_lifetime_minutes"] == 60


def test_patch_logs_audit_with_changed_fields(auth_client, admin_user):
    client = auth_client(admin_user)
    client.patch("/api/settings/", {"login_lockout_threshold": 9}, format="json")
    entry = AuditLog.objects.filter(action="UPDATE", target_type="SystemSettings").latest(
        "created_at"
    )
    assert entry.details.get("changed_fields") == ["login_lockout_threshold"]
    assert entry.user == admin_user


# ---------------------------------------------------------------------------
# Cache: signal invalidation + TTL backstop
# ---------------------------------------------------------------------------


def test_get_settings_is_cached_and_invalidated_on_save(admin_user):
    first = get_settings()
    assert cache.get(CACHE_KEY) is not None
    assert first.login_lockout_threshold == 5

    obj = SystemSettings.objects.get(pk=1)
    obj.login_lockout_threshold = 11
    obj.save()  # post_save signal should invalidate the cache immediately

    second = get_settings()
    assert second.login_lockout_threshold == 11


def test_get_settings_falls_back_to_defaults_on_db_failure(monkeypatch):
    invalidate_settings_cache()

    def _boom(*args, **kwargs):
        raise RuntimeError("db down")

    monkeypatch.setattr(SystemSettings.objects, "first", _boom)
    result = get_settings()
    assert result.login_lockout_threshold == 5
    assert result.default_page_size == 20


# ---------------------------------------------------------------------------
# Reset to defaults
# ---------------------------------------------------------------------------


def test_admin_can_reset_to_defaults(auth_client, admin_user):
    client = auth_client(admin_user)
    client.patch(
        "/api/settings/",
        {"login_lockout_threshold": 42, "default_page_size": 99},
        format="json",
    )
    res = client.post("/api/settings/reset/", {}, format="json")
    assert res.status_code == 200
    assert res.data["login_lockout_threshold"] == 5
    assert res.data["default_page_size"] == 20

    reset_entry = AuditLog.objects.filter(action="SETTINGS_RESET").latest("created_at")
    assert reset_entry.user == admin_user
    # Distinct from the ordinary PATCH diff entries above.
    assert not AuditLog.objects.filter(
        action="UPDATE", target_type="SystemSettings"
    ).latest("created_at").action == "SETTINGS_RESET"


def test_it_cannot_reset(auth_client, it_user):
    res = auth_client(it_user).post("/api/settings/reset/", {}, format="json")
    assert res.status_code == 403


def test_other_role_cannot_reset(auth_client, doctor_user):
    res = auth_client(doctor_user).post("/api/settings/reset/", {}, format="json")
    assert res.status_code == 403


# ---------------------------------------------------------------------------
# Runtime enforcement: lockout
# ---------------------------------------------------------------------------


def test_lockout_threshold_is_configurable(api_client, admin_user, doctor_user, auth_client):
    auth_client(admin_user).patch(
        "/api/settings/", {"login_lockout_threshold": 2}, format="json"
    )
    for _ in range(2):
        res = api_client.post(
            "/api/auth/login/",
            {"username": "doctor", "password": "wrong"},
            format="json",
        )
        assert res.status_code == 401
    doctor_user.refresh_from_db()
    assert doctor_user.is_locked

    res = api_client.post(
        "/api/auth/login/",
        {"username": "doctor", "password": "pass12345"},
        format="json",
    )
    assert res.status_code == 423


# ---------------------------------------------------------------------------
# Runtime enforcement: login throttle
# ---------------------------------------------------------------------------


def test_login_rate_limit_is_configurable(admin_user, doctor_user, auth_client):
    auth_client(admin_user).patch(
        "/api/settings/", {"login_rate_limit_per_min": 3}, format="json"
    )
    # A fresh, never-force-authenticated client: AnonRateThrottle.get_cache_key
    # returns None (skipping throttling entirely) for an authenticated
    # request, and `api_client`/`auth_client` share one force_authenticate'd
    # instance -- reusing it here would silently never throttle.
    from rest_framework.test import APIClient

    anon_client = APIClient()
    statuses = []
    for _ in range(4):
        res = anon_client.post(
            "/api/auth/login/",
            {"username": "doctor", "password": "wrong"},
            format="json",
        )
        statuses.append(res.status_code)
    assert 429 in statuses


# ---------------------------------------------------------------------------
# Runtime enforcement: password minimum length
# ---------------------------------------------------------------------------


def test_password_min_length_is_configurable(auth_client, admin_user):
    client = auth_client(admin_user)
    client.patch("/api/settings/", {"password_min_length": 12}, format="json")
    res = client.post(
        "/api/auth/users/",
        {
            "username": "shortpass",
            "password": "short12",
            "first_name": "A",
            "last_name": "B",
            "role": "RECEPTIONIST",
        },
        format="json",
    )
    assert res.status_code == 400
    assert "password" in res.data


# ---------------------------------------------------------------------------
# Runtime enforcement: max image upload size
# ---------------------------------------------------------------------------


def _png_bytes(width=10, height=10):
    buf = io.BytesIO()
    Image.new("RGB", (width, height), color="red").save(buf, format="PNG")
    buf.seek(0)
    return buf.read()


def test_max_image_upload_size_is_configurable(auth_client, admin_user, doctor_user):
    patient = Patient.objects.create(
        first_name="Jane", last_name="Doe", gender="FEMALE",
        phone="8095550100", address="123 Main St", email="jane@example.com",
    )
    record = MedicalRecord.objects.create(
        patient=patient, created_by=doctor_user, title="Note", diagnosis="D"
    )

    admin_client = auth_client(admin_user)
    admin_client.patch("/api/settings/", {"max_image_upload_mb": 1}, format="json")

    from django.core.files.uploadedfile import SimpleUploadedFile

    # ~1.5 MB payload padded past PNG data with a comment chunk stand-in
    # (any bytes work here, size is what's checked before the PIL decode).
    oversized = _png_bytes() + b"0" * (2 * 1024 * 1024)
    upload = SimpleUploadedFile("big.png", oversized, content_type="image/png")

    res = auth_client(doctor_user).post(
        "/api/images/",
        {"record": record.id, "image": upload, "caption": "too big"},
        format="multipart",
    )
    assert res.status_code == 400
    assert "image" in res.data


def test_upload_limits_endpoint_reflects_configured_value(auth_client, admin_user, doctor_user):
    auth_client(admin_user).patch("/api/settings/", {"max_image_upload_mb": 42}, format="json")
    res = auth_client(doctor_user).get("/api/records/upload-limits/")
    assert res.status_code == 200
    assert res.data["max_image_upload_mb"] == 42


def test_upload_limits_endpoint_denies_receptionist(auth_client, receptionist_user):
    res = auth_client(receptionist_user).get("/api/records/upload-limits/")
    assert res.status_code == 403


# ---------------------------------------------------------------------------
# Runtime enforcement: media token TTL
# ---------------------------------------------------------------------------


def test_media_token_ttl_is_read_from_settings(auth_client, admin_user, monkeypatch):
    auth_client(admin_user).patch(
        "/api/settings/", {"media_token_ttl_minutes": 5}, format="json"
    )

    captured = {}

    def _fake_verify(file_path, token, max_age=None):
        captured["max_age"] = max_age
        return False

    monkeypatch.setattr("apps.core.services.verify_media_token", _fake_verify)

    api_client = auth_client(admin_user)
    api_client.get("/media/some/path.png?token=abc")
    assert captured["max_age"] == 5 * 60


# ---------------------------------------------------------------------------
# Runtime enforcement: default page size
# ---------------------------------------------------------------------------


def test_default_page_size_is_configurable(auth_client, admin_user):
    for i in range(8):
        Patient.objects.create(first_name=f"P{i}", last_name="X")

    client = auth_client(admin_user)
    client.patch("/api/settings/", {"default_page_size": 5}, format="json")

    res = client.get("/api/patients/")
    assert res.status_code == 200
    assert len(res.data["results"]) == 5
    assert res.data["count"] == 8

    # An explicit ?page_size= still overrides the configured default.
    res = client.get("/api/patients/?page_size=6")
    assert len(res.data["results"]) == 6


# ---------------------------------------------------------------------------
# Runtime enforcement: JWT access-token lifetime (lifetime-as-@property)
# ---------------------------------------------------------------------------


def test_access_token_lifetime_is_live_per_issuance(api_client, admin_user, auth_client):
    auth_client(admin_user).patch(
        "/api/settings/", {"access_token_lifetime_minutes": 5}, format="json"
    )
    res = api_client.post(
        "/api/auth/login/",
        {"username": "admin", "password": "pass12345"},
        format="json",
    )
    assert res.status_code == 200
    token = UntypedToken(res.data["access"])
    lifetime_seconds = token.payload["exp"] - token.payload["iat"]
    assert lifetime_seconds == 5 * 60
