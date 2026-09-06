from django.core.cache import cache
from drf_spectacular.views import SpectacularAPIView
from rest_framework.response import Response

SCHEMA_CACHE_TTL = 60 * 60


class CachedSpectacularAPIView(SpectacularAPIView):
    """The generated OpenAPI schema is CPU-heavy to build and static in
    content, so cache it.

    ``get()`` is only ever called by DRF's ``dispatch()`` after
    ``check_permissions()`` has already run and passed (``SERVE_PERMISSIONS``
    = ``IsAdminOrIT``), so caching here — unlike wrapping the URL with
    Django's ``cache_page``, which intercepts the request *before* dispatch
    and its permission check — never risks serving a cached response to a
    caller who hasn't been authorized for this request.
    """

    def get(self, request, *args, **kwargs):
        key = f"schema:v1:{request.get_full_path()}"
        cached = cache.get(key)
        if cached is not None:
            data, headers = cached
            return Response(data, headers=headers)
        response = super().get(request, *args, **kwargs)
        if response.status_code == 200:
            cache.set(
                key,
                (response.data, dict(response.headers)),
                timeout=SCHEMA_CACHE_TTL,
            )
        return response
