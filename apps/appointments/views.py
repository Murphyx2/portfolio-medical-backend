from django.db import transaction
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import serializers, viewsets
from rest_framework.decorators import action
from rest_framework.filters import OrderingFilter, SearchFilter
from rest_framework.response import Response

from apps.appointments.models import Appointment
from apps.appointments.serializers import AppointmentSerializer
from apps.core.mixins import AuditMixin, SwapPermissionsMixin
from apps.core.permissions import (
    CanCancelAppointment,
    CanCompleteAppointment,
    CanDeleteAppointments,
    CanManageAppointments,
    IsStaffUser,
)
from apps.core.services import scope_queryset


class AppointmentViewSet(SwapPermissionsMixin, AuditMixin, viewsets.ModelViewSet):
    queryset = Appointment.all_objects.select_related(
        "patient", "doctor__user", "center", "service", "created_by"
    )
    serializer_class = AppointmentSerializer
    permission_classes = [IsStaffUser]
    write_permission_classes = [CanManageAppointments]
    delete_permission_classes = [CanDeleteAppointments]
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_fields = {
        "patient": ["exact"],
        "doctor": ["exact"],
        "center": ["exact"],
        "status": ["exact"],
        "date_time": ["exact", "gte", "lt"],
    }
    search_fields = [
        "patient__search_name",
        "doctor__user__last_name",
        "center__name",
        "status",
    ]
    ordering_fields = [
        "date_time",
        "patient__search_name",
        "doctor__user__last_name",
        "center__name",
        "status",
    ]

    def get_queryset(self):
        return scope_queryset(super().get_queryset(), self.request.user, owner_field="doctor__user")

    def get_permissions(self):
        permissions = super().get_permissions()
        # cancel/complete are custom @action POST routes, so
        # SwapPermissionsMixin's method-keyed swap (above, via
        # super().get_permissions()) lands on write_permission_classes for
        # both -- narrow further per self.action here instead of the inline
        # self.permission_denied() checks this used to hand-roll.
        if self.action == "cancel":
            return [CanCancelAppointment()]
        if self.action == "complete":
            return [CanCompleteAppointment()]
        return permissions

    @transaction.atomic
    def perform_create(self, serializer):
        self.perform_create_with_owner(serializer, "created_by")

    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        appointment = self.get_object()
        if appointment.status in (Appointment.Status.CANCELLED, Appointment.Status.COMPLETED):
            raise serializers.ValidationError(
                {"detail": "This appointment is already closed."}
            )
        reason = (request.data.get("reason") or "").strip()
        if not reason:
            raise serializers.ValidationError(
                {"reason": "A cancellation reason is required."}
            )
        appointment.status = Appointment.Status.CANCELLED
        appointment.cancel_reason = reason
        appointment.save(update_fields=["status", "cancel_reason"])
        self.log_action(appointment, "UPDATE", details={"status": "CANCELLED", "reason": reason})
        return Response(self.get_serializer(appointment).data)

    @action(detail=True, methods=["post"])
    def complete(self, request, pk=None):
        appointment = self.get_object()
        if appointment.status in (Appointment.Status.CANCELLED, Appointment.Status.COMPLETED):
            raise serializers.ValidationError(
                {"detail": "This appointment is already closed."}
            )
        appointment.status = Appointment.Status.COMPLETED
        appointment.save()
        self.log_action(appointment, "UPDATE", details={"status": "COMPLETED"})
        return Response(self.get_serializer(appointment).data)

    @action(detail=True, methods=["post"])
    def reschedule(self, request, pk=None):
        """Lightweight single-field (date_time only) update, distinct from a
        full PATCH -- keeps the frontend's Reschedule dialog a one-field
        form and makes the write intent explicit for permission/audit
        purposes (same gate as a general edit: CanManageAppointments)."""
        appointment = self.get_object()
        if appointment.status in (Appointment.Status.CANCELLED, Appointment.Status.COMPLETED):
            raise serializers.ValidationError(
                {"detail": "This appointment is already closed."}
            )
        serializer = self.get_serializer(
            appointment, data={"date_time": request.data.get("date_time")}, partial=True
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        self.log_action(appointment, "UPDATE", details={"date_time": serializer.data["date_time"]})
        return Response(serializer.data)
