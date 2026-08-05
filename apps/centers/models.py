from django.conf import settings
from django.db import models

from apps.core.models import TimestampedModel


class MedicalCenter(TimestampedModel):
    name = models.CharField(max_length=200)
    code = models.CharField(max_length=20, unique=True)
    address = models.CharField(max_length=300)
    phone = models.CharField(max_length=30)
    email = models.EmailField(blank=True)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class DoctorCenterBinding(TimestampedModel):
    """Binds a doctor to a medical center; access requires admin approval."""

    doctor = models.ForeignKey(
        "doctors.DoctorProfile",
        on_delete=models.CASCADE,
        related_name="center_bindings",
    )
    center = models.ForeignKey(
        MedicalCenter,
        on_delete=models.CASCADE,
        related_name="doctor_bindings",
    )
    approved = models.BooleanField(default=False)
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="approved_bindings",
    )

    class Meta:
        ordering = ["center", "doctor"]
        unique_together = ("doctor", "center")

    def __str__(self) -> str:
        status = "approved" if self.approved else "pending"
        return f"{self.doctor} @ {self.center} ({status})"
