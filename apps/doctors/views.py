from django.db import IntegrityError
from rest_framework import serializers, viewsets
from rest_framework.permissions import SAFE_METHODS

from apps.core.mixins import AuditMixin
from apps.core.permissions import IsAdminOrIT, IsDoctor, IsStaffUser
from apps.doctors.models import DoctorProfile, DoctorSchedule
from apps.doctors.serializers import DoctorProfileSerializer, DoctorScheduleSerializer


class DoctorProfileViewSet(AuditMixin, viewsets.ModelViewSet):
    queryset = DoctorProfile.objects.select_related("user").all()
    serializer_class = DoctorProfileSerializer
    permission_classes = [IsStaffUser]
    filterset_fields = ["specialty", "user"]

    def get_permissions(self):
        if self.request.method not in SAFE_METHODS:
            self.permission_classes = [IsAdminOrIT]
        return super().get_permissions()

    def get_queryset(self):
        qs = super().get_queryset()
        if getattr(self.request.user, "is_doctor", False):
            qs = qs.filter(user=self.request.user)
        return qs

    def perform_create(self, serializer):
        try:
            super().perform_create(serializer)
        except IntegrityError:
            raise serializers.ValidationError(
                {"user": "This user already has a doctor profile."}
            )

    def perform_update(self, serializer):
        try:
            super().perform_update(serializer)
        except IntegrityError:
            raise serializers.ValidationError(
                {"user": "This user already has a doctor profile."}
            )


class DoctorScheduleViewSet(AuditMixin, viewsets.ModelViewSet):
    queryset = DoctorSchedule.objects.select_related("doctor__user", "center").all()
    serializer_class = DoctorScheduleSerializer
    permission_classes = [IsStaffUser]
    filterset_fields = ["doctor", "center", "weekday"]

    def get_permissions(self):
        if self.request.method not in SAFE_METHODS:
            self.permission_classes = [IsDoctor]
        return super().get_permissions()

    def get_queryset(self):
        qs = super().get_queryset()
        if getattr(self.request.user, "is_doctor", False):
            qs = qs.filter(doctor__user=self.request.user)
        return qs
