from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import viewsets
from rest_framework.filters import OrderingFilter, SearchFilter

from apps.ars.models import ARS
from apps.ars.serializers import ARSSerializer
from apps.core.caching import CachedListViewMixin
from apps.core.mixins import AuditMixin, SwapPermissionsMixin
from apps.core.permissions import IsAdmin, IsStaffUser


class ARSViewSet(SwapPermissionsMixin, AuditMixin, CachedListViewMixin, viewsets.ModelViewSet):
    cache_model = "ars"
    queryset = ARS.all_objects.prefetch_related("programs")
    serializer_class = ARSSerializer
    permission_classes = [IsStaffUser]
    write_permission_classes = [IsAdmin]
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_fields = ["name"]
    search_fields = ["ars_id", "name"]
    ordering_fields = ["ars_id", "name"]
