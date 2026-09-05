from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import viewsets
from rest_framework.filters import OrderingFilter

from apps.core.mixins import AuditMixin, SwapPermissionsMixin
from apps.core.permissions import CanDeletePatient, PatientDataPermission
from apps.core.services import is_masked_role, scope_queryset
from apps.patients.filters import PatientSearchFilter
from apps.patients.models import Patient
from apps.patients.serializers import PatientSerializer


class PatientViewSet(SwapPermissionsMixin, AuditMixin, viewsets.ModelViewSet):
    queryset = Patient.all_objects.select_related(
        "ars", "ars_program", "center"
    ).prefetch_related("extra_phones", "guardians").all()
    serializer_class = PatientSerializer
    permission_classes = [PatientDataPermission]
    delete_permission_classes = [CanDeletePatient]
    filter_backends = [DjangoFilterBackend, PatientSearchFilter, OrderingFilter]
    filterset_fields = ["search_name", "gender", "ars", "center"]
    ordering_fields = [
        "search_name",
        "gender",
        "ars__name",
        "ars_program__name",
        "center__name",
    ]

    def perform_create(self, serializer):
        super().perform_create(serializer)
        from apps.records.services import create_initial_record

        create_initial_record(
            serializer.instance, self.request.user, request=self.request
        )

    def get_queryset(self):
        # scope_doctors=False: doctor visibility on Patients is intentionally
        # unrestricted (see test_security_fixes.py::
        # test_doctor_sees_patients_across_all_centers) -- only non-doctor
        # staff (receptionist/IT/nurse/center manager) get center-scoped.
        qs = scope_queryset(super().get_queryset(), self.request.user, scope_doctors=False)
        user = self.request.user
        if is_masked_role(user):
            # IT/CENTER_MANAGER must not be able to confirm whether a specific
            # name is a patient (plaintext search_name would defeat display
            # masking and act as a PII-existence oracle). Setting this as an
            # *instance* attribute (not overriding a method) is the pattern
            # DjangoFilterBackend actually expects for a per-request field
            # list -- it reads `getattr(view, "filterset_fields", None)"
            # directly (see get_filterset_class()), with no method hook to
            # override instead.
            self.filterset_fields = ["gender", "ars", "center"]
        return qs
