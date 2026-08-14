from django.db import transaction
from django.utils import timezone
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import serializers, viewsets
from rest_framework.decorators import action
from rest_framework.filters import OrderingFilter, SearchFilter
from rest_framework.permissions import SAFE_METHODS
from rest_framework.response import Response

from apps.core.caching import CachedListViewMixin
from apps.core.mixins import AuditMixin
from apps.core.permissions import CanManageEncounters, IsAdminOrIT, IsStaffUser
from apps.core.services import client_ip, log_audit
from apps.encounters.models import Encounter, EncounterType, generate_encounter_number
from apps.encounters.serializers import EncounterSerializer, EncounterTypeSerializer


class EncounterTypeViewSet(AuditMixin, CachedListViewMixin, viewsets.ModelViewSet):
    cache_model = "encountertype"
    queryset = EncounterType.all_objects.all()
    serializer_class = EncounterTypeSerializer
    permission_classes = [IsStaffUser]
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    search_fields = ["name"]
    ordering_fields = ["name"]

    def get_permissions(self):
        if self.request.method == "DELETE":
            self.permission_classes = [IsAdminOrIT]
        elif self.action != "restore" and self.request.method not in SAFE_METHODS:
            self.permission_classes = [IsAdminOrIT]
        return super().get_permissions()


class EncounterViewSet(AuditMixin, viewsets.ModelViewSet):
    queryset = Encounter.all_objects.select_related(
        "patient", "doctor__user", "room", "center", "encounter_type", "ars", "ars_program",
        "created_by",
    ).prefetch_related("diagnoses", "services__service", "services__doctor__user")
    serializer_class = EncounterSerializer
    permission_classes = [IsStaffUser]
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_fields = {
        "patient": ["exact"],
        "doctor": ["exact"],
        "center": ["exact"],
        "status": ["exact"],
        "encounter_type": ["exact"],
        "created_at": ["gte", "lt"],
    }
    search_fields = [
        "encounter_number",
        "patient__search_name",
        "doctor__user__last_name",
        "chief_complaint",
    ]
    ordering_fields = ["created_at", "admitted_at", "status", "priority", "patient__search_name"]

    def get_permissions(self):
        if self.request.method == "DELETE":
            self.permission_classes = [IsAdminOrIT]
        elif self.action != "restore" and self.request.method not in SAFE_METHODS:
            self.permission_classes = [CanManageEncounters]
        return super().get_permissions()

    def get_queryset(self):
        qs = super().get_queryset()
        user = self.request.user
        if getattr(user, "is_doctor", False):
            qs = qs.filter(doctor__user=user)
        return qs

    @transaction.atomic
    def perform_create(self, serializer):
        instance = serializer.save()
        log_audit(
            user=self.request.user,
            action="CREATE",
            target=instance,
            ip_address=client_ip(self.request),
        )

    @action(detail=True, methods=["post"])
    def admit(self, request, pk=None):
        encounter = self.get_object()
        if encounter.status != Encounter.Status.DRAFT:
            raise serializers.ValidationError(
                {"detail": "Only a draft encounter can be admitted."}
            )
        errors = encounter.ready_for_active()
        if errors:
            raise serializers.ValidationError({"detail": errors})

        override = bool(request.data.get("override_conflict"))
        today = timezone.localdate()
        conflict = (
            Encounter.objects.filter(
                patient=encounter.patient,
                status=Encounter.Status.ACTIVE,
                admitted_at__date=today,
            )
            .exclude(pk=encounter.pk)
            .exists()
        )
        if conflict and not override:
            raise serializers.ValidationError(
                {
                    "code": "ACTIVE_ENCOUNTER_EXISTS",
                    "detail": "This patient already has an active encounter today.",
                }
            )

        with transaction.atomic():
            encounter.status = Encounter.Status.ACTIVE
            encounter.admitted_at = timezone.now()
            encounter.save(update_fields=["status", "admitted_at"])
            generate_encounter_number(encounter, today=today)
        encounter.refresh_from_db()
        log_audit(
            user=request.user,
            action="UPDATE",
            target=encounter,
            ip_address=client_ip(request),
            details={"status": "ACTIVE", "encounter_number": encounter.encounter_number},
        )
        return Response(self.get_serializer(encounter).data)

    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        encounter = self.get_object()
        if encounter.status in (Encounter.Status.COMPLETED, Encounter.Status.CANCELLED):
            raise serializers.ValidationError(
                {"detail": "This encounter is already closed."}
            )
        encounter.status = Encounter.Status.CANCELLED
        encounter.cancel_reason = (request.data.get("reason") or "").strip()
        encounter.save(update_fields=["status", "cancel_reason"])
        log_audit(
            user=request.user,
            action="UPDATE",
            target=encounter,
            ip_address=client_ip(request),
            details={"status": "CANCELLED", "reason": encounter.cancel_reason},
        )
        return Response(self.get_serializer(encounter).data)

    @action(detail=True, methods=["post"])
    def complete(self, request, pk=None):
        encounter = self.get_object()
        if encounter.status != Encounter.Status.ACTIVE:
            raise serializers.ValidationError(
                {"detail": "Only an active encounter can be completed."}
            )
        encounter.status = Encounter.Status.COMPLETED
        encounter.completed_at = timezone.now()
        encounter.save(update_fields=["status", "completed_at"])
        log_audit(
            user=request.user,
            action="UPDATE",
            target=encounter,
            ip_address=client_ip(request),
            details={"status": "COMPLETED"},
        )
        return Response(self.get_serializer(encounter).data)
