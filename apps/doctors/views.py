from django.db import IntegrityError
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import serializers, viewsets
from rest_framework.filters import OrderingFilter, SearchFilter
from rest_framework.permissions import SAFE_METHODS

from apps.core.mixins import AuditMixin
from apps.core.permissions import IsAdminOrIT, IsDoctor, IsStaffUser
from apps.doctors.models import DoctorProfile, DoctorSchedule
from apps.doctors.serializers import DoctorProfileSerializer, DoctorScheduleSerializer


class DoctorProfileViewSet(AuditMixin, viewsets.ModelViewSet):
    queryset = DoctorProfile.all_objects.select_related("user").all()
    serializer_class = DoctorProfileSerializer
    permission_classes = [IsStaffUser]
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_fields = ["specialty", "user"]
    search_fields = [
        "code",
        "user__first_name",
        "user__last_name",
        "license_number",
        "specialty",
        "contact_email",
        "contact_phone",
    ]
    ordering_fields = [
        "code",
        "user__last_name",
        "user__first_name",
        "specialty",
        "license_number",
        "contact_email",
        "contact_phone",
    ]

    def get_permissions(self):
        if self.request.method not in SAFE_METHODS:
            self.permission_classes = [IsAdminOrIT]
        return super().get_permissions()

    def get_queryset(self):
        qs = super().get_queryset()
        if getattr(self.request.user, "is_doctor", False):
            qs = qs.filter(user=self.request.user)
        return qs

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
        if user.is_active:
            user.is_active = False
            user.save(update_fields=["is_active"])
            self._audit("UPDATE", user)


class DoctorScheduleViewSet(AuditMixin, viewsets.ModelViewSet):
    queryset = DoctorSchedule.all_objects.select_related("doctor__user", "center").all()
    serializer_class = DoctorScheduleSerializer
    permission_classes = [IsStaffUser]
    filterset_fields = ["doctor", "center", "weekday"]

    def get_permissions(self):
        if self.request.method not in SAFE_METHODS:
            self.permission_classes = [IsDoctor]
        return super().get_permissions()

    def get_queryset(self):
        qs = super().get_queryset()
        if getattr(self.request.user, "is_doctor", False):
            qs = qs.filter(doctor__user=self.request.user)
        return qs
