from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import viewsets
from rest_framework.filters import OrderingFilter, SearchFilter
from rest_framework.permissions import SAFE_METHODS

from apps.core.caching import CachedListViewMixin
from apps.core.mixins import AuditMixin
from apps.core.permissions import CanManageMedicines, IsAdminOrIT, IsStaffUser
from apps.medicines.models import Medicine
from apps.medicines.serializers import MedicineSerializer


class MedicineViewSet(AuditMixin, CachedListViewMixin, viewsets.ModelViewSet):
    cache_model = "medicine"
    queryset = Medicine.all_objects.all()
    serializer_class = MedicineSerializer
    permission_classes = [IsStaffUser]
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_fields = ["generic_name", "commercial_name"]
    search_fields = ["generic_name", "commercial_name", "concentration"]
    ordering_fields = ["generic_name", "commercial_name", "concentration"]

    def get_permissions(self):
        if self.request.method == "DELETE":
            self.permission_classes = [IsAdminOrIT]
        elif self.request.method not in SAFE_METHODS:
            self.permission_classes = [CanManageMedicines]
        return super().get_permissions()
