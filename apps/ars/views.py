from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import viewsets
from rest_framework.filters import OrderingFilter, SearchFilter
from rest_framework.permissions import SAFE_METHODS

from apps.ars.models import ARS
from apps.ars.serializers import ARSSerializer
from apps.core.caching import CachedListViewMixin
from apps.core.mixins import AuditMixin
from apps.core.permissions import IsAdminOrReceptionist, IsStaffUser


class ARSViewSet(AuditMixin, CachedListViewMixin, viewsets.ModelViewSet):
    cache_model = "ars"
    queryset = ARS.all_objects.prefetch_related("programs")
    serializer_class = ARSSerializer
    permission_classes = [IsStaffUser]
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_fields = ["name"]
    search_fields = ["ars_id", "name"]
    ordering_fields = ["ars_id", "name"]

    def get_permissions(self):
        if self.request.method not in SAFE_METHODS:
            self.permission_classes = [IsAdminOrReceptionist]
        return super().get_permissions()
