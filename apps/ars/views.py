from rest_framework import viewsets
from rest_framework.permissions import SAFE_METHODS

from apps.ars.models import ARS
from apps.ars.serializers import ARSSerializer
from apps.core.mixins import AuditMixin
from apps.core.permissions import IsAdminOrReceptionist, IsStaffUser


class ARSViewSet(AuditMixin, viewsets.ModelViewSet):
    queryset = ARS.objects.prefetch_related("programs")
    serializer_class = ARSSerializer
    permission_classes = [IsStaffUser]
    filterset_fields = ["name"]

    def get_permissions(self):
        if self.request.method not in SAFE_METHODS:
            self.permission_classes = [IsAdminOrReceptionist]
        return super().get_permissions()
