from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import viewsets
from rest_framework.filters import OrderingFilter, SearchFilter

from apps.core.caching import CachedListViewMixin
from apps.core.mixins import AuditMixin, SwapPermissionsMixin
from apps.core.permissions import CanManageMedicines, IsAdminOrIT, IsStaffUser
from apps.medicines.models import Medicine
from apps.medicines.serializers import MedicineSerializer


class MedicineViewSet(
    SwapPermissionsMixin, AuditMixin, CachedListViewMixin, viewsets.ModelViewSet
):
    cache_model = "medicine"
    queryset = Medicine.all_objects.all()
    serializer_class = MedicineSerializer
    permission_classes = [IsStaffUser]
    write_permission_classes = [CanManageMedicines]
    delete_permission_classes = [IsAdminOrIT]
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_fields = ["generic_name", "commercial_name"]
    search_fields = ["generic_name", "commercial_name", "concentration"]
    ordering_fields = ["generic_name", "commercial_name", "concentration"]
