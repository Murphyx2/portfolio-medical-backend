from django.db import transaction
from django.utils import timezone
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import serializers, viewsets
from rest_framework.decorators import action
from rest_framework.filters import OrderingFilter
from rest_framework.response import Response

from apps.core.mixins import AuditMixin, SwapPermissionsMixin
from apps.core.permissions import CanManageEncounters, IsAdminOrIT, IsStaffUser
from apps.core.services import client_ip, log_audit, scope_queryset
from apps.encounters.filters import EncounterSearchFilter
from apps.encounters.models import Encounter, generate_encounter_number
from apps.encounters.serializers import EncounterSerializer


class EncounterViewSet(SwapPermissionsMixin, AuditMixin, viewsets.ModelViewSet):
    queryset = Encounter.all_objects.select_related(
        "patient", "patient__ars", "patient__ars_program",
        "doctor__user", "room", "center", "service_type", "ars", "ars_program",
        "created_by",
    ).prefetch_related("diagnoses", "services__service", "services__doctor__user")
    serializer_class = EncounterSerializer
    permission_classes = [IsStaffUser]
    write_permission_classes = [CanManageEncounters]
    delete_permission_classes = [IsAdminOrIT]
    filter_backends = [DjangoFilterBackend, EncounterSearchFilter, OrderingFilter]
    filterset_fields = {
        "patient": ["exact"],
        "doctor": ["exact"],
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
        "doctor__code",
    ]

    def get_queryset(self):
        return scope_queryset(super().get_queryset(), self.request.user, owner_field="doctor__user")

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
        self.log_action(
            encounter,
            "UPDATE",
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
