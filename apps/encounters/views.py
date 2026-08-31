from django.db import transaction
from django.utils import timezone
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import serializers, viewsets
from rest_framework.decorators import action
from rest_framework.filters import OrderingFilter
from rest_framework.response import Response

from apps.appointments.services import complete_todays_appointments_for_patient
from apps.core.mixins import AuditMixin, SwapPermissionsMixin
from apps.core.permissions import CanManageEncounters, IsAdminOrITOrCenterManager, IsStaffUser
from apps.core.services import scope_queryset
from apps.encounters.filters import EncounterSearchFilter
from apps.encounters.models import Encounter, EncounterAdmitError
from apps.encounters.serializers import EncounterSerializer


class EncounterViewSet(SwapPermissionsMixin, AuditMixin, viewsets.ModelViewSet):
    queryset = Encounter.all_objects.select_related(
        "patient", "patient__ars", "patient__ars_program",
        "center", "service_type", "ars", "ars_program",
        "created_by",
    ).prefetch_related(
        "diagnoses", "services__service", "services__doctor__user", "services__room",
        "patient__guardians",
    )
    serializer_class = EncounterSerializer
    permission_classes = [IsStaffUser]
    write_permission_classes = [CanManageEncounters]
    delete_permission_classes = [IsAdminOrITOrCenterManager]
    filter_backends = [DjangoFilterBackend, EncounterSearchFilter, OrderingFilter]
    filterset_fields = {
        "patient": ["exact"],
        "services__doctor": ["exact"],
        "center": ["exact"],
        "status": ["exact"],
        "service_type": ["exact"],
        "created_at": ["gte", "lt"],
    }
    ordering_fields = [
        "created_at",
        "admitted_at",
        "status",
        "priority",
        "patient__search_name",
    ]

    def get_queryset(self):
        return scope_queryset(
            super().get_queryset(), self.request.user, owner_field="services__doctor__user"
        ).distinct()

    @transaction.atomic
    def perform_create(self, serializer):
        super().perform_create(serializer)

    @action(detail=True, methods=["post"])
    def admit(self, request, pk=None):
        encounter = self.get_object()
        override = bool(request.data.get("override_conflict"))
        try:
            encounter.admit(override_conflict=override)
        except EncounterAdmitError as exc:
            payload = {"detail": exc.detail}
            if exc.code:
                payload["code"] = exc.code
            raise serializers.ValidationError(payload)
        self.log_action(
            encounter,
            "UPDATE",
            details={"status": "ACTIVE", "encounter_number": encounter.encounter_number},
        )
        complete_todays_appointments_for_patient(
            encounter.patient, timezone.localtime(encounter.admitted_at).date(), request.user, request=request
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
        self.log_action(
            encounter, "UPDATE", details={"status": "CANCELLED", "reason": encounter.cancel_reason}
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
        self.log_action(encounter, "UPDATE", details={"status": "COMPLETED"})
        return Response(self.get_serializer(encounter).data)
