from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import viewsets
from rest_framework.filters import OrderingFilter, SearchFilter

from apps.core.caching import CachedListViewMixin
from apps.core.mixins import AuditMixin, SwapPermissionsMixin
from apps.core.permissions import IsAdminOrCenterManager, IsStaffUser
from apps.services.models import Service, ServiceType
from apps.services.serializers import ServiceSerializer, ServiceTypeSerializer


class ServiceTypeViewSet(
    SwapPermissionsMixin, AuditMixin, CachedListViewMixin, viewsets.ModelViewSet
):
    cache_model = "servicetype"
    queryset = ServiceType.all_objects.all()
    serializer_class = ServiceTypeSerializer
    permission_classes = [IsStaffUser]
    write_permission_classes = [IsAdminOrCenterManager]
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    search_fields = ["name"]
    ordering_fields = ["name"]


class ServiceViewSet(SwapPermissionsMixin, AuditMixin, CachedListViewMixin, viewsets.ModelViewSet):
    cache_model = "service"
    queryset = Service.all_objects.select_related("type").all()
    serializer_class = ServiceSerializer
    permission_classes = [IsStaffUser]
    write_permission_classes = [IsAdminOrCenterManager]
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_fields = ["type"]
    search_fields = ["name", "simon"]
    ordering_fields = ["name", "simon", "co_pago", "privado"]
