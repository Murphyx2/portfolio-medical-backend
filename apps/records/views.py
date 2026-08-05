from django.db import transaction
from django.db.models import Q
from rest_framework import viewsets
from rest_framework.permissions import SAFE_METHODS

from apps.core.mixins import AuditMixin
from apps.core.permissions import (
    CanManageRecords,
    IsDoctorOrNurse,
    IsStaffUser,
)
from apps.core.services import user_accessible_center_ids
from apps.records.models import ConsultationLog, MedicalRecord, RecordImage
from apps.records.serializers import (
    ConsultationLogSerializer,
    MedicalRecordSerializer,
    RecordImageSerializer,
)


class MedicalRecordViewSet(AuditMixin, viewsets.ModelViewSet):
    queryset = MedicalRecord.objects.select_related(
        "patient", "created_by", "center"
    ).prefetch_related("images")
    serializer_class = MedicalRecordSerializer
    permission_classes = [IsStaffUser]
    filterset_fields = ["patient", "center", "title"]
    search_fields = ["title", "patient__first_name", "patient__last_name"]

    def get_permissions(self):
        if self.request.method not in SAFE_METHODS:
            self.permission_classes = [CanManageRecords]
        return super().get_permissions()

    def get_queryset(self):
        qs = super().get_queryset()
        user = self.request.user
        if getattr(user, "is_doctor", False):
            center_ids = user_accessible_center_ids(user)
            qs = qs.filter(Q(center_id__in=center_ids) | Q(created_by=user))
        return qs

    @transaction.atomic
    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)


class ConsultationLogViewSet(AuditMixin, viewsets.ModelViewSet):
    queryset = ConsultationLog.objects.select_related("patient", "doctor", "center")
    serializer_class = ConsultationLogSerializer
    permission_classes = [IsStaffUser]
    filterset_fields = ["patient", "center", "doctor"]

    def get_permissions(self):
        if self.request.method not in SAFE_METHODS:
            self.permission_classes = [CanManageRecords]
        return super().get_permissions()

    def get_queryset(self):
        qs = super().get_queryset()
        user = self.request.user
        if getattr(user, "is_doctor", False):
            center_ids = user_accessible_center_ids(user)
            qs = qs.filter(Q(center_id__in=center_ids) | Q(doctor=user))
        return qs

    @transaction.atomic
    def perform_create(self, serializer):
        serializer.save(doctor=self.request.user)


class RecordImageViewSet(AuditMixin, viewsets.ModelViewSet):
    queryset = RecordImage.objects.select_related("record", "uploaded_by")
    serializer_class = RecordImageSerializer
    permission_classes = [IsStaffUser]
    filterset_fields = ["record"]

    def get_permissions(self):
        if self.request.method not in SAFE_METHODS:
            self.permission_classes = [CanManageRecords]
        return super().get_permissions()

    @transaction.atomic
    def perform_create(self, serializer):
        serializer.save(uploaded_by=self.request.user)
