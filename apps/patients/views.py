from rest_framework import viewsets

from apps.core.mixins import AuditMixin
from apps.core.permissions import PatientDataPermission
from apps.patients.models import Patient
from apps.patients.serializers import PatientSerializer


class PatientViewSet(AuditMixin, viewsets.ModelViewSet):
    queryset = Patient.objects.all()
    serializer_class = PatientSerializer
    permission_classes = [PatientDataPermission]
    filterset_fields = ["first_name", "last_name", "gender"]
    search_fields = ["first_name", "last_name", "email"]
