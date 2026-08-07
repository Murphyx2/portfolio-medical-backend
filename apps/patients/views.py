from django.db.models import Q
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import viewsets
from rest_framework.filters import OrderingFilter

from apps.core.mixins import AuditMixin
from apps.core.permissions import PatientDataPermission
from apps.core.services import is_masked_role, user_accessible_center_ids
from apps.patients.filters import PatientSearchFilter, patient_age
from apps.patients.models import Patient
from apps.patients.serializers import PatientSerializer

# Encrypted-at-rest columns cannot be ordered in SQL; they are sorted in Python
# after decryption (see `list`/`_python_sorted_rows`).
_PYTHON_ORDER_FIELDS = {"phone", "email", "cedula", "nss", "age"}


class PatientViewSet(AuditMixin, viewsets.ModelViewSet):
    queryset = Patient.objects.all()
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
            center_ids = user_accessible_center_ids(user)
            # Centerless patients are unbound (visible); center-bound patients
            # are visible only to their center's doctors (or via their records).
            qs = qs.filter(
                Q(center_id__isnull=True)
                | Q(center_id__in=center_ids)
                | Q(medical_records__center_id__in=center_ids)
            ).distinct()
        return qs

    def list(self, request, *args, **kwargs):
        ordering = request.query_params.get("ordering", "")
        field = ordering.lstrip("-")
        if field in _PYTHON_ORDER_FIELDS:
            return self._python_sorted_list(request, field, ordering.startswith("-"))
        return super().list(request, *args, **kwargs)

    def _python_sorted_list(self, request, field, reverse):
        qs = self.filter_queryset(self.get_queryset())
        if field == "age":
            rows = self._python_sorted_rows(qs, lambda p: patient_age(p), reverse)
        else:
            rows = self._python_sorted_rows(
                qs, lambda p: str(getattr(p, field) or "").lower(), reverse
            )
        page = self.paginate_queryset(rows)
        serializer = self.get_serializer(page, many=True)
        return self.get_paginated_response(serializer.data)

    @staticmethod
    def _python_sorted_rows(rows, key, reverse):
        """Sort a queryset/list by a decrypted value; None values go last
        regardless of direction."""
        present = [r for r in rows if key(r) is not None]
        absent = [r for r in rows if key(r) is None]
        present.sort(key=key, reverse=reverse)
        return present + absent
