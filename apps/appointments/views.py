from django.db import transaction
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.filters import OrderingFilter, SearchFilter
from rest_framework.permissions import SAFE_METHODS
from rest_framework.response import Response

from apps.appointments.models import Appointment
from apps.appointments.serializers import AppointmentSerializer
from apps.core.mixins import AuditMixin
from apps.core.permissions import CanDeleteAppointments, CanManageAppointments, IsStaffUser
from apps.core.services import client_ip, log_audit, user_accessible_center_ids


class AppointmentViewSet(AuditMixin, viewsets.ModelViewSet):
    queryset = Appointment.all_objects.select_related(
        "patient", "doctor__user", "center", "created_by"
    )
    serializer_class = AppointmentSerializer
    permission_classes = [IsStaffUser]
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

    def get_permissions(self):
        if self.request.method == "DELETE":
            self.permission_classes = [CanDeleteAppointments]
        elif self.request.method not in SAFE_METHODS:
            self.permission_classes = [CanManageAppointments]
        return super().get_permissions()

    def get_queryset(self):
        qs = super().get_queryset()
        user = self.request.user
        if getattr(user, "is_doctor", False):
            qs = qs.filter(doctor__user=user)
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
        log_audit(
            user=request.user,
            action="UPDATE",
            target=appointment,
            ip_address=client_ip(request),
            details={"status": "CANCELLED"},
        )
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
        log_audit(
            user=request.user,
            action="UPDATE",
            target=appointment,
            ip_address=client_ip(request),
            details={"status": "COMPLETED"},
        )
        return Response(self.get_serializer(appointment).data)
