from django.core.validators import MinValueValidator, RegexValidator
from django.db import models

from apps.core.models import SoftDeleteModel, TimestampedModel


class ServiceType(TimestampedModel, SoftDeleteModel):
    name = models.CharField(max_length=255, unique=True)
    # Drive the Admission form: not every service needs a doctor present
    # (e.g. a lab-only visit) or a primary diagnosis to admit (e.g. a
    # routine vaccination) -- see apps/encounters/models.py::Encounter.
    requires_doctor = models.BooleanField(default=False)
    requires_diagnosis = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class Service(TimestampedModel, SoftDeleteModel):
    simon = models.CharField(
        max_length=6,
        validators=[RegexValidator(r"^\d{1,6}$", "SIMON must be 1-6 digits.")],
        verbose_name="SIMON",
    )
    name = models.CharField(max_length=255)
    type = models.ForeignKey(ServiceType, on_delete=models.PROTECT, related_name="services")
    co_pago = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(0)],
        verbose_name="Co-pago",
    )
    privado = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(0)],
    )

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return f"{self.name} ({self.simon})"
