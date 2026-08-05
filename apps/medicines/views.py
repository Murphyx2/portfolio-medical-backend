from rest_framework import viewsets
from rest_framework.permissions import SAFE_METHODS

from apps.core.mixins import AuditMixin
from apps.core.permissions import IsAdminOrIT, IsStaffUser
from apps.medicines.models import Medicine
from apps.medicines.serializers import MedicineSerializer


class MedicineViewSet(AuditMixin, viewsets.ModelViewSet):
    queryset = Medicine.objects.all()
    serializer_class = MedicineSerializer
    permission_classes = [IsStaffUser]
    filterset_fields = ["generic_name", "commercial_name"]
    search_fields = ["generic_name", "commercial_name"]

    def get_permissions(self):
        if self.request.method not in SAFE_METHODS:
            self.permission_classes = [IsAdminOrIT]
        return super().get_permissions()
