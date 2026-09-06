from django.db.models import Count
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.centers.models import DoctorCenterBinding, MedicalCenter
from apps.centers.serializers import DoctorCenterBindingSerializer, MedicalCenterSerializer
from apps.core.mixins import AuditMixin, SwapPermissionsMixin
from apps.core.permissions import IsAdminOrCenterManager, IsStaffUser
from apps.core.viewsets import ReferenceDataViewSet


class MedicalCenterViewSet(ReferenceDataViewSet):
    """Centers are visible to nobody but ADMIN/CENTER_MANAGER (admin-
    equivalent) -- every other role, including IT (which could previously
    write here), is fully excluded, per the decision to hide the Centers
    page from all non-admin roles."""

    queryset = MedicalCenter.all_objects.annotate(
        doctor_count=Count("doctor_bindings")
    ).order_by("name")
    serializer_class = MedicalCenterSerializer
    permission_classes = [IsAdminOrCenterManager]
    filterset_fields = ["name", "code"]
    search_fields = ["name", "code", "address", "phone", "email"]
    ordering_fields = ["name", "code", "address", "phone", "email", "doctor_count"]


class DoctorCenterBindingViewSet(SwapPermissionsMixin, AuditMixin, viewsets.ModelViewSet):
    queryset = DoctorCenterBinding.all_objects.select_related("doctor__user", "center")
    serializer_class = DoctorCenterBindingSerializer
    permission_classes = [IsStaffUser]
    write_permission_classes = [IsAdminOrCenterManager]
    filterset_fields = ["doctor", "center", "approved"]

    def get_queryset(self):
        qs = super().get_queryset()
        if getattr(self.request.user, "is_doctor", False):
            qs = qs.filter(doctor__user=self.request.user)
        return qs

    def perform_create(self, serializer):
        serializer.save(approved_by=self.request.user, approved=True)

    @action(detail=True, methods=["post"])
    def approve(self, request, pk=None):
        binding = self.get_object()
        if not (
            getattr(request.user, "is_admin", False)
            or getattr(request.user, "is_center_manager", False)
        ):
            self.permission_denied(
                request, message="Only admins or center managers can approve bindings."
            )
        binding.approved = True
        binding.approved_by = request.user
        binding.save()
        self.log_action(binding, "UPDATE", details={"approved": True})
        return Response(self.get_serializer(binding).data)
