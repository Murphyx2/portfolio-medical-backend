"""Server-side caching for the safe, auth-agnostic reference lists.

Only non-PHI lookup data (medicines, ARS insurers/programs, medical centers) is
cached. Patients, records, appointments and doctor profiles carry PII or
role-specific masking and must never be cached server-side (M-05 asserts the
``Cache-Control: no-store`` response header for them).

The cached lists are identical for every authenticated staff member -- with
one exception: admin requests carrying ``?include_inactive=true`` see a
different (wider) result set than everyone else for the same URL, so those
specific requests bypass the cache entirely (read and write) rather than
risk serving one role's response to another. This is low-volume traffic
(admin-only, opt-in), so skipping the cache for it is simpler and safer than
adding a role dimension to every cache key. Writes bump a per-model version
counter (``apps.core.signals``, wired to ``post_save``/``post_delete`` so
Django-admin edits invalidate the cache too, not just API writes) so a newly
created, updated, or deactivated medicine/ARS/center shows up on the very
next request instead of waiting for the TTL to expire.
"""

from django.core.cache import cache
from rest_framework.response import Response

from apps.core.services import can_view_inactive

CACHE_TTL = 300
# Version counters never expire (they are tiny and must outlive the data keys
# they invalidate, which have a TTL of CACHE_TTL).
CACHE_VERSION_TTL = None

# Model -> set of cached list keys to invalidate when a row of that model
# changes. arsprogram writes go through the ARS serializer but are mapped to
# the ARS list too, and doctor bindings feed the center doctor_count.
_CACHE_INVALIDATION_MAP = {
    "medicine": ("medicine",),
    "ars": ("ars",),
    "arsprogram": ("ars", "arsprogram"),
    "medicalcenter": ("medicalcenter",),
    "doctorcenterbinding": ("medicalcenter", "doctorcenterbinding"),
}


def _version_key(model: str) -> str:
    return f"ref:v:{model}"


def invalidate_model(model: str) -> None:
    """Bump the version counter for a cached model: keys built under the
    previous version become stale and are rebuilt on the next request."""
    key = _version_key(model)
    try:
        cache.incr(key)
    except ValueError:
        cache.set(key, 1, timeout=CACHE_VERSION_TTL)


def invalidate_for_instance(instance) -> None:
    """Invalidate every cached list affected by a change to ``instance``."""
    names = _CACHE_INVALIDATION_MAP.get(type(instance).__name__.lower())
    if names:
        for name in names:
            invalidate_model(name)


def list_cache_key(model: str, request) -> str:
    version = cache.get(_version_key(model)) or "0"
    return f"ref:{model}:v{version}:{request.get_full_path()}"


class CachedListViewMixin:
    """Mix into a ViewSet whose ``list()`` output is identical for every
    authenticated staff member (no PII, no per-role masking, no per-user
    query scoping) to cache it server-side.

    Set ``cache_model`` to the key used in ``_CACHE_INVALIDATION_MAP`` above
    and wired to a signal receiver in ``apps.core.signals``.

    The permission layer still runs first: DRF's ``dispatch()`` calls
    ``check_permissions()`` before ``list()`` is ever invoked, so this cache
    lookup only ever executes for a request that already passed the view's
    ``permission_classes`` — unlike wrapping the endpoint with Django's
    ``cache_page`` at the URL level, which intercepts the request *before*
    permissions are checked and would risk serving one user's cached
    response to another who shouldn't see it.

    Only 200 responses are stored, and only for authenticated requests.
    ``next``/``previous`` are dropped because they embed the first
    requester's absolute URLs.
    """

    cache_model: str = ""
    cache_ttl: int = CACHE_TTL

    def list(self, request, *args, **kwargs):
        user = getattr(request, "user", None)
        if not (user and getattr(user, "is_authenticated", False)):
            return super().list(request, *args, **kwargs)
        if (
            can_view_inactive(user)
            and request.query_params.get("include_inactive", "").lower() == "true"
        ):
            return super().list(request, *args, **kwargs)
        key = list_cache_key(self.cache_model, request)
        cached = cache.get(key)
        if cached is not None:
            return Response(cached)
        response = super().list(request, *args, **kwargs)
        if response.status_code == 200:
            payload = response.data
            if isinstance(payload, dict):
                payload = {
                    k: v for k, v in payload.items() if k not in ("next", "previous")
                }
            cache.set(key, payload, timeout=self.cache_ttl)
        return response
