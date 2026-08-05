from django.conf import settings
from django.db import models

from apps.core.models import TimestampedModel


class Appointment(TimestampedModel):
    """Appointment created by a doctor or a receptionist for a patient."""

    class Status(models.TextChoices):
        SCHEDULED = "SCHEDULED", "Scheduled"
        CONFIRMED = "CONFIRMED", "Confirmed"
        COMPLETED = "COMPLETED", "Completed"
        CANCELLED = "CANCELLED", "Cancelled"
        NO_SHOW = "NO_SHOW", "No show"

    patient = models.ForeignKey(
        "patients.Patient",
        on_delete=models.CASCADE,
        related_name="appointments",
    )
    doctor = models.ForeignKey(
        "doctors.DoctorProfile",
        on_delete=models.PROTECT,
        related_name="appointments",
    )
    center = models.ForeignKey(
        "centers.MedicalCenter",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="appointments",
    )
    date_time = models.DateTimeField()
    duration_minutes = models.PositiveSmallIntegerField(default=30)
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.SCHEDULED,
    )
    notes = models.TextField(blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_appointments",
    )

    class Meta:
        ordering = ["date_time"]
        indexes = [
            models.Index(fields=["date_time", "status"]),
            models.Index(fields=["doctor", "date_time"]),
        ]

    def __str__(self) -> str:
        return f"{self.patient.full_name} @ {self.date_time:%Y-%m-%d %H:%M}"
