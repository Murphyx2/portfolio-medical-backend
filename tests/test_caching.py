"""Server-side caching of the non-PHI reference lists (medicines, ARS,
medical centers) and the OpenAPI schema (apps/core/caching.py, signals.py,
views.py::CachedSpectacularAPIView).

Security invariants under test:
- PHI/masked endpoints (patients, records, appointments) are never cached —
  a stale server-side cache would defeat role-based masking and is exactly
  what M-05's Cache-Control: no-store guards against (see
  test_fix_m_01_07.py).
- The schema cache is populated *after* permission checks, not before — a
  cached admin response must never leak to a caller who isn't Admin/IT
  (this is the difference between caching inside get() vs wrapping the URL
  with Django's cache_page, which would intercept the request before
  dispatch() runs check_permissions()).
- Invalidation is signal-based (post_save/post_delete on the model), so it
  fires regardless of whether the write came through the DRF API or
  Django admin — not tied to the DRF-only AuditMixin hook.
"""

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from apps.ars.models import ARS
from apps.centers.models import DoctorCenterBinding, MedicalCenter
from apps.doctors.models import DoctorProfile
from apps.medicines.models import Medicine
from apps.patients.models import Patient
from apps.rooms.models import Room, RoomType
from apps.services.models import Service, ServicePrice, ServiceType


def _query_count(client, url):
    with CaptureQueriesContext(connection) as ctx:
        res = client.get(url)
    return res, len(ctx.captured_queries)


# ---------------------------------------------------------------------------
# medicines / ARS / centers: cache hit + invalidation
# ---------------------------------------------------------------------------


def test_medicine_list_second_request_is_served_from_cache(auth_client, admin_user, db):
    Medicine.objects.create(generic_name="Amoxicilina", commercial_name="Amox")
    client = auth_client(admin_user)

    res1, n1 = _query_count(client, "/api/medicines/")
    assert res1.status_code == 200
    assert n1 > 0

    res2, n2 = _query_count(client, "/api/medicines/")
    assert res2.status_code == 200
    assert n2 == 0
    # The cached payload intentionally drops next/previous (they'd embed the
    # first requester's absolute URL); compare the parts the SPA cares about.
    assert res2.data["count"] == res1.data["count"]
    assert res2.data["results"] == res1.data["results"]


def test_medicine_create_via_api_invalidates_cache_immediately(
    auth_client, admin_user, db
):
    client = auth_client(admin_user)
    assert client.get("/api/medicines/").data["count"] == 0

    res = client.post(
        "/api/medicines/",
        {"generic_name": "Ibuprofeno", "commercial_name": "Brufen", "concentration": "400mg"},
        format="json",
    )
    assert res.status_code == 201

    assert client.get("/api/medicines/").data["count"] == 1


def test_medicine_created_outside_the_api_still_invalidates_cache(
    auth_client, admin_user, db
):
    """Writes made through Django admin (or any direct model .save(), a
    management command, a data migration...) never go through DRF's
    AuditMixin/perform_create — only the post_save signal fires for all of
    them alike. This is the scenario the AuditMixin-hook design (considered
    and rejected) would have missed."""
    client = auth_client(admin_user)
    assert client.get("/api/medicines/").data["count"] == 0

    Medicine.objects.create(generic_name="Paracetamol", commercial_name="Tylenol")

    assert client.get("/api/medicines/").data["count"] == 1


def test_medicine_delete_invalidates_cache(auth_client, admin_user, db):
    med = Medicine.objects.create(generic_name="Amoxicilina", commercial_name="Amox")
    client = auth_client(admin_user)
    assert client.get("/api/medicines/").data["count"] == 1

    client.delete(f"/api/medicines/{med.id}/")

    assert client.get("/api/medicines/").data["count"] == 0


def test_room_type_list_cached_and_invalidated(auth_client, admin_user, db):
    """RoomType list is cached like the other reference lists; create /
    rename / delete must invalidate it immediately, not after the TTL
    (regression: RoomType was cached but never wired to an invalidation
    signal, so changes were invisible for up to 300s)."""
    client = auth_client(admin_user)
    res1, n1 = _query_count(client, "/api/room-types/")
    assert res1.status_code == 200
    assert n1 > 0
    res2, n2 = _query_count(client, "/api/room-types/")
    assert n2 == 0
    assert res2.data["count"] == res1.data["count"]
    assert res2.data["results"] == res1.data["results"]

    rt = RoomType.objects.create(name="Consulta externa")
    assert client.get("/api/room-types/").data["count"] == res1.data["count"] + 1

    client.patch(f"/api/room-types/{rt.id}/", {"name": "Emergencia"}, format="json")
    renamed = client.get("/api/room-types/").data["results"]
    assert any(r["name"] == "EMERGENCIA" for r in renamed)

    client.delete(f"/api/room-types/{rt.id}/")
    assert client.get("/api/room-types/").data["count"] == res1.data["count"]


def test_ars_list_cached_and_invalidated(auth_client, admin_user, db):
    # ARS/ARSProgram are seeded (SEMMA/SENASA) by a data migration, so start
    # from whatever count is already there rather than assuming empty.
    client = auth_client(admin_user)
    res1, n1 = _query_count(client, "/api/ars/")
    assert n1 > 0
    baseline = res1.data["count"]
    res2, n2 = _query_count(client, "/api/ars/")
    assert n2 == 0
    assert res2.data["count"] == res1.data["count"]
    assert res2.data["results"] == res1.data["results"]

    ARS.objects.create(ars_id="Q1", name="Insurer Q")
    assert client.get("/api/ars/").data["count"] == baseline + 1


def test_room_list_cached_and_invalidated(auth_client, admin_user, db):
    center = MedicalCenter.objects.create(
        name="Central", code="C1", address="Addr", phone="8095550000"
    )
    room_type = RoomType.objects.create(name="Consultorio")
    client = auth_client(admin_user)
    res1, n1 = _query_count(client, "/api/rooms/")
    assert n1 > 0
    res2, n2 = _query_count(client, "/api/rooms/")
    assert n2 == 0
    assert res2.data["count"] == res1.data["count"]

    room = Room.objects.create(code="R1", name="Room 1", center=center, room_type=room_type)
    assert client.get("/api/rooms/").data["count"] == res1.data["count"] + 1

    room.delete()
    assert client.get("/api/rooms/").data["count"] == res1.data["count"]


def test_service_type_list_cached_and_invalidated(auth_client, admin_user, db):
    client = auth_client(admin_user)
    res1, n1 = _query_count(client, "/api/service-types/")
    assert n1 > 0
    res2, n2 = _query_count(client, "/api/service-types/")
    assert n2 == 0
    assert res2.data["count"] == res1.data["count"]

    st = ServiceType.objects.create(name="Laboratorio")
    assert client.get("/api/service-types/").data["count"] == res1.data["count"] + 1

    st.delete()
    assert client.get("/api/service-types/").data["count"] == res1.data["count"]


def test_service_list_cached_and_invalidated(auth_client, admin_user, db):
    service_type = ServiceType.objects.create(name="Laboratorio")
    client = auth_client(admin_user)
    res1, n1 = _query_count(client, "/api/services/")
    assert n1 > 0
    res2, n2 = _query_count(client, "/api/services/")
    assert n2 == 0
    assert res2.data["count"] == res1.data["count"]

    service = Service.objects.create(
        simon="100001", name="Lab test", type=service_type, co_pago=0, privado=0
    )
    assert client.get("/api/services/").data["count"] == res1.data["count"] + 1

    service.delete()
    assert client.get("/api/services/").data["count"] == res1.data["count"]


def test_service_price_list_cached_and_invalidated(auth_client, admin_user, db):
    """Regression: ServicePrice was missing from _CACHE_INVALIDATION_MAP and
    the signals registry, so a create through the API landed in the DB but
    the very next list request kept serving the stale cached (pre-create)
    response -- indistinguishable from the write silently failing."""
    service_type = ServiceType.objects.create(name="Laboratorio")
    service = Service.objects.create(
        simon="100002", name="Lab test", type=service_type, co_pago=0, privado=0
    )
    ars = ARS.objects.create(ars_id="TA", name="Test ARS")
    client = auth_client(admin_user)
    res1, n1 = _query_count(client, "/api/service-prices/")
    assert n1 > 0
    res2, n2 = _query_count(client, "/api/service-prices/")
    assert n2 == 0
    assert res2.data["count"] == res1.data["count"]

    price = ServicePrice.objects.create(service=service, ars=ars, co_pago="300.00")
    assert client.get("/api/service-prices/").data["count"] == res1.data["count"] + 1

    price.delete()
    assert client.get("/api/service-prices/").data["count"] == res1.data["count"]


def test_doctor_center_binding_approval_invalidates_center_list_cache(
    auth_client, admin_user, doctor_user, db
):
    """Centers list embeds doctor_count; approving a binding must be
    reflected immediately, not after the cache TTL."""
    center = MedicalCenter.objects.create(
        name="Central", code="C1", address="Addr", phone="8095550000"
    )
    profile = DoctorProfile.objects.create(
        user=doctor_user, license_number="L1", contact_phone="8095550001"
    )
    client = auth_client(admin_user)
    assert client.get("/api/centers/").data["results"][0]["doctor_count"] == 0

    binding = DoctorCenterBinding.objects.create(
        doctor=profile, center=center, approved=False, approved_by=admin_user
    )
    client.post(f"/api/bindings/{binding.id}/approve/")

    assert client.get("/api/centers/").data["results"][0]["doctor_count"] == 1


# ---------------------------------------------------------------------------
# PHI endpoints must never be cached
# ---------------------------------------------------------------------------


def test_patients_list_is_never_cached(auth_client, admin_user, db):
    client = auth_client(admin_user)
    assert client.get("/api/patients/").data["count"] == 0

    # Created directly (not via the API) so nothing about *this* write could
    # coincidentally trigger the reference-data invalidation signals above —
    # if patients were (mistakenly) cached, this second request would still
    # return the stale (empty) result.
    Patient.objects.create(first_name="Ana", last_name="Perez")

    assert client.get("/api/patients/").data["count"] == 1


# ---------------------------------------------------------------------------
# schema caching: content is cached, but only after permission checks
# ---------------------------------------------------------------------------


def test_schema_second_request_is_served_from_cache(auth_client, admin_user, db):
    client = auth_client(admin_user)
    # Prime the SystemSettings cache outside the measured block -- every
    # request now runs through SettingsAnonRateThrottle/SettingsUserRateThrottle
    # (apps/core/throttling.py), whose get_rate() reads it; the first read
    # after the autouse clear_cache fixture is a cache miss (one extra DB
    # query) that has nothing to do with schema generation itself.
    from apps.systemsettings.services import get_settings

    get_settings()
    res1, n1 = _query_count(client, "/api/schema/")
    assert res1.status_code == 200
    assert n1 == 0  # schema generation touches no DB rows either way

    res2 = client.get("/api/schema/")
    assert res2.status_code == 200
    assert res2.data == res1.data


def test_schema_cache_does_not_leak_across_permission_boundary(
    auth_client, admin_user, doctor_user, db
):
    """Warm the cache as an authorized user, then confirm a caller who is
    NOT Admin/IT still gets 403 — proving the cache lookup happens inside
    get() (after check_permissions()) rather than around the whole view."""
    auth_client(admin_user).get("/api/schema/")

    res = auth_client(doctor_user).get("/api/schema/")
    assert res.status_code == 403


def test_schema_cache_unreachable_anonymously(auth_client, admin_user, db):
    auth_client(admin_user).get("/api/schema/")

    # A genuinely separate, unauthenticated client — note the auth_client
    # fixture mutates (force_authenticate) the *same* APIClient instance the
    # api_client fixture would hand back, so reusing that fixture here would
    # not actually be anonymous.
    from rest_framework.test import APIClient

    assert APIClient().get("/api/schema/").status_code == 401


# ---------------------------------------------------------------------------
# _CACHE_INVALIDATION_MAP / connect_cache_invalidation() must stay in sync
# ---------------------------------------------------------------------------


def test_connect_cache_invalidation_raises_on_unknown_map_key():
    """B5 regression guard: connect_cache_invalidation() derives its signal
    connections from _CACHE_INVALIDATION_MAP's keys, so a key with no
    matching model must fail loudly at startup instead of silently leaving
    that model's writes un-invalidated."""
    from unittest.mock import patch

    from django.core.exceptions import ImproperlyConfigured

    from apps.core import caching, signals

    bad_map = dict(caching._CACHE_INVALIDATION_MAP)
    bad_map["not_a_real_model"] = ("medicine",)

    with patch.object(caching, "_CACHE_INVALIDATION_MAP", bad_map):
        with patch.object(signals, "_CACHE_INVALIDATION_MAP", bad_map):
            with pytest.raises(ImproperlyConfigured):
                signals.connect_cache_invalidation()
