import mimetypes
from pathlib import Path

from django.conf import settings
from django.db import transaction
from django.db.models import Q
from django.http import FileResponse
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import status, viewsets
from rest_framework.filters import OrderingFilter
from rest_framework.permissions import SAFE_METHODS
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.mixins import AuditMixin
from apps.core.permissions import (
    CanManageRecords,
    IsDoctorOrNurse,
    IsStaffUser,
)
from apps.core.services import client_ip, log_audit, user_accessible_center_ids
from apps.records.filters import RecordSearchFilter
from apps.records.models import ConsultationLog, MedicalRecord, RecordImage
from apps.records.serializers import (
    ConsultationLogSerializer,
    MedicalRecordSerializer,
    RecordImageSerializer,
)


class MedicalRecordViewSet(AuditMixin, viewsets.ModelViewSet):
    queryset = MedicalRecord.all_objects.select_related(
        "patient", "created_by", "center"
    ).prefetch_related("images")
    serializer_class = MedicalRecordSerializer
    permission_classes = [IsStaffUser]
    filter_backends = [DjangoFilterBackend, RecordSearchFilter, OrderingFilter]
    filterset_fields = ["patient", "center", "title"]
    ordering_fields = ["date", "title", "patient__search_name", "created_by__username"]

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
        log_audit(
            user=self.request.user,
            action="CREATE",
            target=serializer.instance,
            ip_address=client_ip(self.request),
        )


class ConsultationLogViewSet(AuditMixin, viewsets.ModelViewSet):
    queryset = ConsultationLog.all_objects.select_related("patient", "doctor", "center")
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
        log_audit(
            user=self.request.user,
            action="CREATE",
            target=serializer.instance,
            ip_address=client_ip(self.request),
        )


class RecordImageViewSet(AuditMixin, viewsets.ModelViewSet):
    queryset = RecordImage.all_objects.select_related("record", "uploaded_by").order_by(
        "-created_at"
    )
    serializer_class = RecordImageSerializer
    permission_classes = [IsStaffUser]
    filterset_fields = ["record"]

    def get_permissions(self):
        if self.request.method not in SAFE_METHODS:
            self.permission_classes = [CanManageRecords]
        return super().get_permissions()

    def get_queryset(self):
        qs = super().get_queryset()
        user = self.request.user
        if getattr(user, "is_doctor", False):
            center_ids = user_accessible_center_ids(user)
            qs = qs.filter(
                Q(record__center_id__in=center_ids) | Q(record__created_by=user)
            )
        return qs

    @transaction.atomic
    def perform_create(self, serializer):
        serializer.save(uploaded_by=self.request.user)
        log_audit(
            user=self.request.user,
            action="CREATE",
            target=serializer.instance,
            ip_address=client_ip(self.request),
        )


class ProtectedMediaView(APIView):
    """Serve files under MEDIA_URL only to holders of a short-lived signed token.

    Browser <img> tags cannot attach JWT headers, so access is authorized by a
    signature (HMAC over the file path + expiry timestamp) issued by the API
    when it serializes the media URL. This replaces unauthenticated static
    serving of /media/.
    """

    permission_classes = []
    authentication_classes = []

    def get(self, request, file_path):
        from apps.core.services import verify_media_token

        token = request.query_params.get("token", "")
        if not token or not verify_media_token(file_path, token):
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        if not RecordImage.objects.filter(image=file_path).exists():
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        media_root = Path(settings.MEDIA_ROOT).resolve()
        full = (media_root / file_path).resolve()
        if not full.is_relative_to(media_root) or not full.is_file():
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        content_type = mimetypes.guess_type(full.name)[0] or "application/octet-stream"
        return FileResponse(full.open("rb"), content_type=content_type)
