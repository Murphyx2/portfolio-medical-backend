from django.db import transaction
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.filters import OrderingFilter, SearchFilter
from rest_framework.response import Response

from apps.appointments.models import Appointment
from apps.appointments.serializers import AppointmentSerializer
from apps.core.mixins import AuditMixin, SwapPermissionsMixin
from apps.core.permissions import CanDeleteAppointments, CanManageAppointments, IsStaffUser
from apps.core.services import scope_queryset


class AppointmentViewSet(SwapPermissionsMixin, AuditMixin, viewsets.ModelViewSet):
    queryset = Appointment.all_objects.select_related(
        "patient", "doctor__user", "center", "created_by"
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

    @transaction.atomic
    def perform_create(self, serializer):
        self.perform_create_with_owner(serializer, "created_by")

    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        appointment = self.get_object()
        if not (
            getattr(request.user, "is_receptionist", False)
            or getattr(request.user, "is_admin", False)
        ):
            self.permission_denied(request, message="Only receptionists or admins may cancel.")
        appointment.status = Appointment.Status.CANCELLED
        appointment.save()
        self.log_action(appointment, "UPDATE", details={"status": "CANCELLED"})
        return Response(self.get_serializer(appointment).data)

    @action(detail=True, methods=["post"])
    def complete(self, request, pk=None):
        appointment = self.get_object()
        if not (
            getattr(request.user, "is_doctor", False)
            or getattr(request.user, "is_admin", False)
        ):
            self.permission_denied(request, message="Only doctors or admins may complete.")
        appointment.status = Appointment.Status.COMPLETED
        appointment.save()
        self.log_action(appointment, "UPDATE", details={"status": "COMPLETED"})
        return Response(self.get_serializer(appointment).data)
