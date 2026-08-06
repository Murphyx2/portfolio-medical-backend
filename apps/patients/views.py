from django.db.models import Q
from rest_framework import viewsets
from rest_framework.filters import SearchFilter
from django_filters.rest_framework import DjangoFilterBackend

from apps.core.mixins import AuditMixin
from apps.core.permissions import PatientDataPermission
from apps.core.services import is_masked_role, user_accessible_center_ids
from apps.patients.models import Patient
from apps.patients.serializers import PatientSerializer


class PatientViewSet(AuditMixin, viewsets.ModelViewSet):
    queryset = Patient.objects.all()
    serializer_class = PatientSerializer
    permission_classes = [PatientDataPermission]
    filter_backends = [DjangoFilterBackend, SearchFilter]
    filterset_fields = ["search_name", "gender", "ars", "center"]
    search_fields = ["search_name"]

    def get_queryset(self):
        qs = super().get_queryset()
        user = self.request.user
        if is_masked_role(user):
            # IT/CENTER_MANAGER must not be able to confirm whether a specific
            # name is a patient (plaintext search_name would defeat display
            # masking and act as a PII-existence oracle).
            self.search_fields = []
            self.filterset_fields = ["gender", "ars", "center"]
        if getattr(user, "is_doctor", False):
            center_ids = user_accessible_center_ids(user)
            # Centerless patients are unbound (visible); center-bound patients
            # are visible only to their center's doctors (or via their records).
            qs = qs.filter(
                Q(center_id__isnull=True)
                | Q(center_id__in=center_ids)
                | Q(medical_records__center_id__in=center_ids)
            ).distinct()
        return qs
