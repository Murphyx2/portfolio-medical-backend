from rest_framework import viewsets
from rest_framework.permissions import SAFE_METHODS

from apps.core.mixins import AuditMixin
from apps.core.permissions import IsStaffUser
from apps.patients.models import Patient
from apps.patients.serializers import PatientSerializer

WRITE_ROLES = ("admin", "doctor", "receptionist")


class PatientViewSet(AuditMixin, viewsets.ModelViewSet):
    queryset = Patient.objects.all()
    serializer_class = PatientSerializer
    permission_classes = [IsStaffUser]
    filterset_fields = ["first_name", "last_name", "gender"]
    search_fields = ["first_name", "last_name", "email"]

    def get_permissions(self):
        if self.request.method not in SAFE_METHODS:
            user = self.request.user
            if not (
                user.is_admin
                or user.is_doctor
                or user.is_receptionist
            ):
                self.permission_denied(
                    self.request,
                    message="Only Admin, Doctor, or Receptionist may modify patient data.",
                )
        return super().get_permissions()
