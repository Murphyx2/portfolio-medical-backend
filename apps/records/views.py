import mimetypes
from pathlib import Path

from django.conf import settings
from django.db import models, transaction
from django.http import FileResponse
from django.shortcuts import get_object_or_404
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import status, viewsets
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.filters import OrderingFilter
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.mixins import AuditMixin, SwapPermissionsMixin
from apps.core.permissions import (
    CanManageRecordEntries,
    CanManageRecords,
    IsAdminDoctorOrNurse,
    IsAdminOrCenterManager,
)
from apps.core.services import scope_queryset
from apps.core.viewsets import ReferenceDataViewSet
from apps.records.filters import NullsLastOrderingFilter, RecordSearchFilter
from apps.records.models import (
    APCategory,
    APType,
    MedicalRecord,
    RecordEntry,
    RecordFamilyCondition,
    RecordImage,
    RecordPersonalCondition,
)
from apps.records.serializers import (
    APCategorySerializer,
    APTypeSerializer,
    MedicalRecordSerializer,
    RecordEntrySerializer,
    RecordFamilyConditionSerializer,
    RecordImageSerializer,
    RecordPersonalConditionSerializer,
)


class MedicalRecordViewSet(SwapPermissionsMixin, AuditMixin, viewsets.ModelViewSet):
    queryset = MedicalRecord.all_objects.select_related(
        "patient", "created_by", "center"
    ).prefetch_related(
        "images",
        "personal_conditions__ap_type",
        "family_conditions__ap_type",
        "patient__guardians",
    )
    serializer_class = MedicalRecordSerializer
    permission_classes = [IsAdminDoctorOrNurse]
    write_permission_classes = [CanManageRecords]
    # Spec §3: soft-deleting an expediente is Admin/CenterManager-only,
    # narrower than the Admin/Doctor/Nurse/CenterManager write gate that
    # covers create/edit.
    delete_permission_classes = [IsAdminOrCenterManager]
    filter_backends = [DjangoFilterBackend, RecordSearchFilter, NullsLastOrderingFilter]
    filterset_fields = ["patient", "center"]
    ordering_fields = ["last_visit_at", "patient__search_name", "created_by__username"]

    def get_queryset(self):
        # scope_doctors=False: doctor visibility on Records is intentionally
        # unrestricted (see test_security_fixes.py::
        # test_record_image_list_is_unscoped_for_doctor and the M-03 comment
        # in that file) -- only non-doctor staff get center-scoped here.
        return scope_queryset(super().get_queryset(), self.request.user, scope_doctors=False)

    @transaction.atomic
    def perform_create(self, serializer):
        self.perform_create_with_owner(serializer, "created_by")


class RecordEntryViewSet(SwapPermissionsMixin, AuditMixin, viewsets.ModelViewSet):
    queryset = RecordEntry.objects.select_related("record", "author")
    serializer_class = RecordEntrySerializer
    permission_classes = [IsAdminDoctorOrNurse]
    write_permission_classes = [CanManageRecordEntries]
    filterset_fields = ["record", "status"]
    ordering_fields = ["completed_at", "created_at"]

    def get_queryset(self):
        return scope_queryset(
            super().get_queryset(), self.request.user, center_field="record__center", scope_doctors=False
        )

    @transaction.atomic
    def perform_create(self, serializer):
        self.perform_create_with_owner(serializer, "author")

    @action(detail=False, methods=["post"])
    def draft(self, request):
        """Idempotent per-user draft upsert -- spec §11: "Exactly one draft
        per expediente per user." Vitals/dx/tx/observaciones are whatever
        the client currently has typed; never touches MedicalRecord's
        last-* cache (only complete() does). Routed through the serializer
        (partial=True) so field-level range validation still applies to a
        draft, same as a completed save -- only the object as a whole being
        incomplete (e.g. one TA part typed so far) is tolerated here, since
        RecordEntrySerializer's cross-field TA-pair check runs regardless;
        the frontend debounce is expected to hold off sending a lone half of
        a TA pair rather than the API silently accepting bad data.
        """
        record_id = request.data.get("record")
        if not record_id:
            return Response({"record": ["This field is required."]}, status=status.HTTP_400_BAD_REQUEST)
        record = get_object_or_404(MedicalRecord.objects, pk=record_id)
        instance = RecordEntry.objects.filter(
            record=record, author=request.user, status=RecordEntry.Status.DRAFT
        ).first()
        serializer = self.get_serializer(instance, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        entry = serializer.save(record=record, author=request.user, status=RecordEntry.Status.DRAFT)
        self.log_action(entry, "UPDATE", details={"draft": True})
        return Response(self.get_serializer(entry).data)

    @action(detail=True, methods=["post"])
    def complete(self, request, pk=None):
        """Draft -> completed (or resave of the last completed entry, for
        "Editar última entrada" -- see RecordEntry.complete())."""
        entry = self.get_object()
        serializer = self.get_serializer(entry, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        try:
            entry.complete(request.user)
        except ValueError:
            return Response(
                {"detail": "No hay cambios para guardar.", "code": "NO_CHANGES"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        self.log_action(entry, "UPDATE", details={"completed": True})
        return Response(self.get_serializer(entry).data)


class RecordPersonalConditionViewSet(SwapPermissionsMixin, AuditMixin, viewsets.ModelViewSet):
    queryset = RecordPersonalCondition.objects.select_related("record", "ap_type")
    serializer_class = RecordPersonalConditionSerializer
    permission_classes = [IsAdminDoctorOrNurse]
    write_permission_classes = [CanManageRecords]
    filterset_fields = ["record"]

    def get_queryset(self):
        return scope_queryset(
            super().get_queryset(), self.request.user, center_field="record__center", scope_doctors=False
        )


class RecordFamilyConditionViewSet(SwapPermissionsMixin, AuditMixin, viewsets.ModelViewSet):
    queryset = RecordFamilyCondition.objects.select_related("record", "ap_type", "related_patient")
    serializer_class = RecordFamilyConditionSerializer
    permission_classes = [IsAdminDoctorOrNurse]
    write_permission_classes = [CanManageRecords]
    filterset_fields = ["record"]

    def get_queryset(self):
        return scope_queryset(
            super().get_queryset(), self.request.user, center_field="record__center", scope_doctors=False
        )


class RecordImageViewSet(SwapPermissionsMixin, AuditMixin, viewsets.ModelViewSet):
    queryset = RecordImage.all_objects.select_related("record", "uploaded_by").order_by(
        "-created_at"
    )
    serializer_class = RecordImageSerializer
    permission_classes = [IsAdminDoctorOrNurse]
    write_permission_classes = [CanManageRecords]
    filterset_fields = ["record"]

    def get_queryset(self):
        return scope_queryset(
            super().get_queryset(), self.request.user, center_field="record__center", scope_doctors=False
        )

    @transaction.atomic
    def perform_create(self, serializer):
        self.perform_create_with_owner(serializer, "uploaded_by")


class APCategoryViewSet(ReferenceDataViewSet):
    queryset = APCategory.all_objects.all()
    serializer_class = APCategorySerializer
    permission_classes = [IsAdminDoctorOrNurse]
    write_permission_classes = [IsAdminOrCenterManager]
    search_fields = ["name"]
    ordering_fields = ["name", "sort_order"]

    def perform_create(self, serializer):
        # sort_order is never client-supplied on create -- always the next
        # free slot at the end of the catalog. Computed against the
        # active-only manager (not all_objects) so a freed number is reused:
        # if the highest-numbered category is later deleted, the next
        # created one gets that same number back instead of always climbing.
        # Editing still lets an admin pick any order explicitly
        # (perform_update is untouched). Mirrors AuditMixin.perform_create's
        # body (can't use super() here since it calls serializer.save() with
        # no way to inject sort_order).
        next_order = (
            APCategory.objects.aggregate(models.Max("sort_order"))["sort_order__max"] or 0
        ) + 1
        serializer.save(sort_order=next_order)
        self._audit("CREATE", serializer.instance)


class APTypeViewSet(ReferenceDataViewSet):
    queryset = APType.all_objects.select_related("category").all()
    serializer_class = APTypeSerializer
    permission_classes = [IsAdminDoctorOrNurse]
    write_permission_classes = [IsAdminOrCenterManager]
    filterset_fields = ["category"]
    search_fields = ["name"]
    ordering_fields = ["name", "sort_order"]

    def perform_create(self, serializer):
        # Auto-increment scoped to the type's own category, matching how
        # ApMultiSelect groups/orders types within each category group.
        # Active-only manager (not all_objects) so a freed number is reused,
        # same reasoning as APCategoryViewSet.perform_create above.
        category = serializer.validated_data["category"]
        next_order = (
            APType.objects.filter(category=category).aggregate(models.Max("sort_order"))[
                "sort_order__max"
            ]
            or 0
        ) + 1
        serializer.save(sort_order=next_order)
        self._audit("CREATE", serializer.instance)


@api_view(["GET"])
@permission_classes([IsAdminDoctorOrNurse])
def upload_limits(request):
    """``GET /api/records/upload-limits/`` -- exposes just the configured
    max-image-upload size to any role that can view/upload record images
    (ADMIN/DOCTOR/NURSE), so the frontend can pre-check a selected file
    before uploading it. A deliberately narrow read of the SystemSettings
    singleton: the full ``/api/settings/`` endpoint is ADMIN/IT-only
    (apps.systemsettings), which doesn't cover doctors/nurses who actually
    perform uploads."""
    from apps.systemsettings.services import get_settings

    return Response({"max_image_upload_mb": get_settings().max_image_upload_mb})


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
        from apps.systemsettings.services import get_settings

        token = request.query_params.get("token", "")
        max_age = get_settings().media_token_ttl_minutes * 60
        if not token or not verify_media_token(file_path, token, max_age=max_age):
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        if not RecordImage.objects.filter(image=file_path).exists():
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        media_root = Path(settings.MEDIA_ROOT).resolve()
        full = (media_root / file_path).resolve()
        if not full.is_relative_to(media_root) or not full.is_file():
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        content_type = mimetypes.guess_type(full.name)[0] or "application/octet-stream"
        return FileResponse(full.open("rb"), content_type=content_type)
