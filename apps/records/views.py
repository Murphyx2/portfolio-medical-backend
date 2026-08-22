import mimetypes
from pathlib import Path

from django.conf import settings
from django.db import transaction
from django.http import FileResponse
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import status, viewsets
from rest_framework.filters import OrderingFilter
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.mixins import AuditMixin, SwapPermissionsMixin
from apps.core.permissions import (
    CanManageRecords,
    IsAdminDoctorOrNurse,
)
from apps.records.filters import RecordSearchFilter
from apps.records.models import ConsultationLog, MedicalRecord, RecordImage
from apps.records.serializers import (
    ConsultationLogSerializer,
    MedicalRecordSerializer,
    RecordImageSerializer,
)


class MedicalRecordViewSet(SwapPermissionsMixin, AuditMixin, viewsets.ModelViewSet):
    queryset = MedicalRecord.all_objects.select_related(
        "patient", "created_by", "center"
    ).prefetch_related("images")
    serializer_class = MedicalRecordSerializer
    permission_classes = [IsAdminDoctorOrNurse]
    write_permission_classes = [CanManageRecords]
    filter_backends = [DjangoFilterBackend, RecordSearchFilter, OrderingFilter]
    filterset_fields = ["patient", "center", "title"]
    ordering_fields = ["date", "title", "patient__search_name", "created_by__username"]

    @transaction.atomic
    def perform_create(self, serializer):
        self.perform_create_with_owner(serializer, "created_by")


class ConsultationLogViewSet(SwapPermissionsMixin, AuditMixin, viewsets.ModelViewSet):
    queryset = ConsultationLog.all_objects.select_related("patient", "doctor", "center")
    serializer_class = ConsultationLogSerializer
    permission_classes = [IsAdminDoctorOrNurse]
    write_permission_classes = [CanManageRecords]
    filterset_fields = ["patient", "center", "doctor"]

    @transaction.atomic
    def perform_create(self, serializer):
        self.perform_create_with_owner(serializer, "doctor")


class RecordImageViewSet(SwapPermissionsMixin, AuditMixin, viewsets.ModelViewSet):
    queryset = RecordImage.all_objects.select_related("record", "uploaded_by").order_by(
        "-created_at"
    )
    serializer_class = RecordImageSerializer
    permission_classes = [IsAdminDoctorOrNurse]
    write_permission_classes = [CanManageRecords]
    filterset_fields = ["record"]

    @transaction.atomic
    def perform_create(self, serializer):
        self.perform_create_with_owner(serializer, "uploaded_by")


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
