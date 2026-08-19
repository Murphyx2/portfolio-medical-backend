from django.db.models import Count
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.filters import OrderingFilter, SearchFilter
from rest_framework.permissions import SAFE_METHODS
from rest_framework.response import Response

from apps.centers.models import DoctorCenterBinding, MedicalCenter
from apps.centers.serializers import (
    DoctorCenterBindingSerializer,
    MedicalCenterSerializer,
)
from apps.core.caching import CachedListViewMixin
from apps.core.mixins import AuditMixin, SwapPermissionsMixin
from apps.core.permissions import IsAdmin, IsAdminOrIT, IsStaffUser


class MedicalCenterViewSet(
    SwapPermissionsMixin, AuditMixin, CachedListViewMixin, viewsets.ModelViewSet
):
    cache_model = "medicalcenter"
    queryset = MedicalCenter.all_objects.annotate(
        doctor_count=Count("doctor_bindings")
    ).order_by("name")
    serializer_class = MedicalCenterSerializer
    permission_classes = [IsStaffUser]
    write_permission_classes = [IsAdminOrIT]
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_fields = ["name", "code"]
    search_fields = ["name", "code", "address", "phone", "email"]
    ordering_fields = ["name", "code", "address", "phone", "email", "doctor_count"]


class DoctorCenterBindingViewSet(AuditMixin, viewsets.ModelViewSet):
    queryset = DoctorCenterBinding.all_objects.select_related("doctor__user", "center")
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
        self.log_action(binding, "UPDATE", details={"approved": True})
        return Response(self.get_serializer(binding).data)
