from django.db import IntegrityError
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import serializers, viewsets
from rest_framework.decorators import action
from rest_framework.filters import OrderingFilter, SearchFilter
from rest_framework.response import Response

from apps.core.mixins import AuditMixin, SwapPermissionsMixin
from apps.core.permissions import (
    CanViewInactive,
    IsAdmin,
    IsAdminOrIT,
    IsAdminOrITOrCenterManager,
    IsDoctor,
    IsStaffUser,
)
from apps.doctors.models import DoctorProfile, DoctorSchedule
from apps.doctors.serializers import DoctorProfileSerializer, DoctorScheduleSerializer


class DoctorProfileViewSet(SwapPermissionsMixin, AuditMixin, viewsets.ModelViewSet):
    queryset = (
        DoctorProfile.all_objects.select_related("user", "default_room")
        .prefetch_related("services", "extra_phones")
        .all()
    )
    serializer_class = DoctorProfileSerializer
    permission_classes = [IsStaffUser]
    # Widened to admit CENTER_MANAGER alongside ADMIN/IT -- this class is
    # method-wide, so DoctorProfileSerializer.validate() is what actually
    # confines a CENTER_MANAGER to the `services` field (see its docstring).
    write_permission_classes = [IsAdminOrITOrCenterManager]
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    # `isnull` lookup added on `user` so the Usuarios "vincular médico
    # existente" picker can query ?user__isnull=true server-side instead of
    # fetching every médico and filtering client-side.
    filterset_fields = {"user": ["exact", "isnull"], "services": ["exact"]}
    search_fields = [
        "code",
        "first_name",
        "last_name",
        "license_number",
        "contact_email",
        "contact_phone",
    ]
    ordering_fields = [
        "code",
        "first_name",
        "last_name",
        "license_number",
        "contact_email",
        "contact_phone",
    ]

    def perform_create(self, serializer):
        try:
            super().perform_create(serializer)
        except IntegrityError:
            raise serializers.ValidationError(
                {"user": "This user already has a doctor profile."}
            )

    def perform_update(self, serializer):
        try:
            super().perform_update(serializer)
        except IntegrityError:
            raise serializers.ValidationError(
                {"user": "This user already has a doctor profile."}
            )

    def perform_destroy(self, instance):
        """Deactivating a doctor also disables their login.

        DoctorProfile.user is a forward OneToOneField (CASCADE points from
        DoctorProfile *to* User), so the generic cascade walk in
        deactivate_with_cascade() -- which only follows CASCADE edges away
        from the instance being deleted -- never reaches User from here; this
        is the one explicit reverse-direction step the app's soft-delete
        design doesn't give for free. Restoring the profile does NOT
        reactivate the User (no auto-cascade-restore, by design) -- an admin
        restores the login separately via the Users page if intended.
        """
        user = instance.user
        super().perform_destroy(instance)
        if user is not None and user.is_active:
            user.is_active = False
            user.save(update_fields=["is_active"])
            self._audit("UPDATE", user)

    def get_permissions(self):
        if self.action == "unlink_account":
            # Admin-only, stricter than the general write_permission_classes
            # (which also admits IT/CenterManager) -- SwapPermissionsMixin's
            # SAFE/non-SAFE swap would otherwise overwrite this since
            # unlink_account is a POST, same bypass DoctorScheduleViewSet
            # uses for `restore`.
            self.permission_classes = [IsAdmin]
            return super(SwapPermissionsMixin, self).get_permissions()
        return super().get_permissions()

    @action(detail=True, methods=["post"])
    def unlink_account(self, request, pk=None):
        """Desvincular cuenta: clears the médico's user link without
        touching or deactivating the User row (unlinking is not deleting)."""
        instance = self.get_object()
        instance.user = None
        instance.save(update_fields=["user"])
        self.log_action(instance, "UPDATE", details={"action": "unlink_account"})
        return Response(self.get_serializer(instance).data)


class DoctorScheduleViewSet(SwapPermissionsMixin, AuditMixin, viewsets.ModelViewSet):
    queryset = DoctorSchedule.all_objects.select_related("doctor__user", "center").all()
    serializer_class = DoctorScheduleSerializer
    permission_classes = [IsStaffUser]
    write_permission_classes = [IsDoctor]
    filterset_fields = ["doctor", "center", "weekday"]

    def get_permissions(self):
        if self.action == "restore":
            # restore is admin-only everywhere (invariant #7); the schedule
            # write permission is IsDoctor, which would otherwise block even
            # the admin from reaching the restore action. Bypasses
            # SwapPermissionsMixin's own SAFE/non-SAFE swap here specifically
            # (restore is a POST, so it would otherwise overwrite this with
            # write_permission_classes) by calling straight past it in the MRO.
            self.permission_classes = [CanViewInactive]
            return super(SwapPermissionsMixin, self).get_permissions()
        return super().get_permissions()

    def get_queryset(self):
        qs = super().get_queryset()
        if getattr(self.request.user, "is_doctor", False):
            qs = qs.filter(doctor__user=self.request.user)
        return qs
