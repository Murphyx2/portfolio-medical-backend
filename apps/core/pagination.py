from rest_framework.pagination import PageNumberPagination

from apps.systemsettings.services import get_settings


class DefaultPagination(PageNumberPagination):
    """Honor `?page_size=` (capped) so the frontend can request bigger pages."""

    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 200

    def get_page_size(self, request):
        # Only the *default* (no ?page_size= given) comes from SystemSettings
        # -- an explicit query param still wins and skips the settings read
        # entirely (avoids an extra cache/DB touch on every already-explicit
        # request), staying capped at max_page_size either way via the base
        # implementation below.
        if self.page_size_query_param not in request.query_params:
            try:
                self.page_size = get_settings().default_page_size
            except Exception:
                pass
        return super().get_page_size(request)
