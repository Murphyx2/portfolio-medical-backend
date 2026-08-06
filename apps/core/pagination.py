from rest_framework.pagination import PageNumberPagination


class DefaultPagination(PageNumberPagination):
    """Honor `?page_size=` (capped) so the frontend can request bigger pages."""

    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 200
