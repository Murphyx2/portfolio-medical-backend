from django.db import transaction
from django.utils import timezone
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import serializers, viewsets
from rest_framework.decorators import action
from rest_framework.filters import OrderingFilter, SearchFilter
from rest_framework.response import Response

from apps.appointments.models import Appointment
from apps.appointments.serializers import AppointmentSerializer
from apps.appointments.services import cancel_noshow_appointments
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
        user = getattr(self.request, "user", None)
        if getattr(user, "is_authenticated", False):
            # Lazy no-show maintenance: no celery/cron in this repo, so any
            # SCHEDULED appointment that's gone stale is auto-cancelled the
            # next time anyone reads the appointments endpoint.
            cancel_noshow_appointments(user, request=self.request)
        return scope_queryset(super().get_queryset(), user, owner_field="doctor__user")

    def get_permissions(self):
        permissions = super().get_permissions()
        # cancel/complete are custom @action POST routes, so
        # SwapPermissionsMixin's method-keyed swap (above, via
        # super().get_permissions()) lands on write_permission_classes for
        # both -- narrow further per self.action here instead of the inline
        # self.permission_denied() checks this used to hand-roll.
        if self.action == "cancel":
            return [CanCancelAppointment()]
        if self.action in ("confirm", "complete"):
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
    def confirm(self, request, pk=None):
        """The patient has confirmed attendance -- an intermediate step
        between SCHEDULED and COMPLETED (see `complete`, which now only
        accepts a CONFIRMED appointment)."""
        appointment = self.get_object()
        if appointment.status != Appointment.Status.SCHEDULED:
            raise serializers.ValidationError(
                {"detail": "Only scheduled appointments can be confirmed."}
            )
        appointment.status = Appointment.Status.CONFIRMED
        appointment.save()
        self.log_action(appointment, "UPDATE", details={"status": "CONFIRMED"})
        return Response(self.get_serializer(appointment).data)

    @action(detail=True, methods=["post"])
    def complete(self, request, pk=None):
        appointment = self.get_object()
        if appointment.status != Appointment.Status.CONFIRMED:
            raise serializers.ValidationError(
                {"detail": "Only confirmed appointments can be completed."}
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

    @action(detail=False, methods=["get"])
    def today_remaining_count(self, request):
        """Badge count for the sidebar's Citas item: SCHEDULED/CONFIRMED
        appointments still ahead today (now..end of day). Goes through
        get_queryset() so it inherits the same auto-cancel maintenance and
        center/doctor scoping the list endpoint already applies."""
        now = timezone.now()
        # .replace(hour=23, ...) must operate on local wall-clock time, not
        # the UTC-stored instant -- USE_TZ=True means now() is UTC internally,
        # and this server's TIME_ZONE (America/Santo_Domingo, UTC-4) makes a
        # naive .replace() on it land on the wrong calendar day near midnight.
        end_of_day = timezone.localtime(now).replace(
            hour=23, minute=59, second=59, microsecond=999999
        )
        count = self.get_queryset().filter(
            status__in=[Appointment.Status.SCHEDULED, Appointment.Status.CONFIRMED],
            date_time__gte=now,
            date_time__lte=end_of_day,
        ).count()
        return Response({"count": count})
