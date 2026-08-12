from django.db.models import Exists, OuterRef, Q
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import viewsets
from rest_framework.filters import OrderingFilter

from apps.core.mixins import AuditMixin
from apps.core.permissions import PatientDataPermission
from apps.core.services import is_masked_role, user_accessible_center_ids
from apps.patients.filters import PatientSearchFilter
from apps.patients.models import Patient
from apps.patients.serializers import PatientSerializer


class PatientViewSet(AuditMixin, viewsets.ModelViewSet):
    queryset = Patient.all_objects.select_related("ars", "ars_program", "center").all()
    serializer_class = PatientSerializer
    permission_classes = [PatientDataPermission]
    filter_backends = [DjangoFilterBackend, PatientSearchFilter, OrderingFilter]
    filterset_fields = ["search_name", "gender", "ars", "center"]
    ordering_fields = [
        "search_name",
        "gender",
        "ars__name",
        "ars_program__name",
        "center__name",
    ]

    def get_queryset(self):
        qs = super().get_queryset()
        user = self.request.user
        if is_masked_role(user):
            # IT/CENTER_MANAGER must not be able to confirm whether a specific
            # name is a patient (plaintext search_name would defeat display
            # masking and act as a PII-existence oracle).
            self.filterset_fields = ["gender", "ars", "center"]
        if getattr(user, "is_doctor", False):
            from apps.records.models import MedicalRecord

            center_ids = user_accessible_center_ids(user)
            # Centerless patients are unbound (visible); center-bound patients
            # are visible only to their center's doctors (or via their records).
            # An EXISTS subquery scopes by records without joining medical_records
            # (avoids row multiplication and the DISTINCT that would follow).
            qs = qs.filter(
                Q(center_id__isnull=True)
                | Q(center_id__in=center_ids)
                | Exists(
                    MedicalRecord.objects.filter(
                        patient_id=OuterRef("pk"), center_id__in=center_ids
                    )
                )
            )
        return qs
