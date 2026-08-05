from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.permissions import SAFE_METHODS
from rest_framework.response import Response

from apps.centers.models import DoctorCenterBinding, MedicalCenter
from apps.centers.serializers import (
    DoctorCenterBindingSerializer,
    MedicalCenterSerializer,
)
from apps.core.mixins import AuditMixin
from apps.core.permissions import IsAdmin, IsAdminOrIT, IsStaffUser
from apps.core.services import client_ip, log_audit


class MedicalCenterViewSet(AuditMixin, viewsets.ModelViewSet):
    queryset = MedicalCenter.objects.all()
    serializer_class = MedicalCenterSerializer
    permission_classes = [IsStaffUser]
    filterset_fields = ["name", "code"]

    def get_permissions(self):
        if self.request.method not in SAFE_METHODS:
            self.permission_classes = [IsAdminOrIT]
        return super().get_permissions()


class DoctorCenterBindingViewSet(AuditMixin, viewsets.ModelViewSet):
    queryset = DoctorCenterBinding.objects.select_related("doctor__user", "center")
    serializer_class = DoctorCenterBindingSerializer
    permission_classes = [IsStaffUser]
    filterset_fields = ["doctor", "center", "approved"]

    def get_queryset(self):
        qs = super().get_queryset()
        if getattr(self.request.user, "is_doctor", False):
            qs = qs.filter(doctor__user=self.request.user)
        return qs

    def get_permissions(self):
        if self.request.method not in SAFE_METHODS:
            self.permission_classes = [IsAdmin]
        return super().get_permissions()

    def perform_create(self, serializer):
        serializer.save(approved_by=self.request.user, approved=True)

    @action(detail=True, methods=["post"])
    def approve(self, request, pk=None):
        binding = self.get_object()
        if not getattr(request.user, "is_admin", False):
            self.permission_denied(request, message="Only admins can approve bindings.")
        binding.approved = True
        binding.approved_by = request.user
        binding.save()
        log_audit(
            user=request.user,
            action="UPDATE",
            target=binding,
            ip_address=client_ip(request),
            details={"approved": True},
        )
        return Response(self.get_serializer(binding).data)
