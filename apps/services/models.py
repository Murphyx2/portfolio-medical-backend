from django.core.validators import MinValueValidator, RegexValidator
from django.db import models

from apps.core.models import SoftDeleteModel, TimestampedModel


class ServiceType(TimestampedModel, SoftDeleteModel):
    name = models.CharField(max_length=255, unique=True)
    # Drive the Admission form: not every service needs a doctor present
    # (e.g. a lab-only visit) or a primary diagnosis to admit (e.g. a
    # routine vaccination) -- see apps/encounters/models.py::Encounter.
    requires_doctor = models.BooleanField(default=False)

    class Meta:
        ordering = ["name"]

    def save(self, *args, **kwargs):
        self.name = self.name.upper()
        super().save(*args, **kwargs)

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

    def save(self, *args, **kwargs):
        self.name = self.name.upper()
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"{self.name} ({self.simon})"


class ServicePrice(TimestampedModel, SoftDeleteModel):
    """A Co-pago override for one Service under a specific ARS, or a
    specific ARS+Program combo -- narrower overrides broader, and if no row
    matches, Service.co_pago is the implicit global default (see
    apps.services.services.resolve_line_price). ``ars`` is required here:
    this table only ever holds overrides above that default, it never
    stores the default itself."""

    service = models.ForeignKey(Service, on_delete=models.CASCADE, related_name="prices")
    ars = models.ForeignKey(
        "ars.ARS", on_delete=models.CASCADE, related_name="service_prices"
    )
    ars_program = models.ForeignKey(
        "ars.ARSProgram",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="service_prices",
    )
    co_pago = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(0)],
        verbose_name="Co-pago",
    )

    class Meta:
        ordering = ["service__name", "ars__name"]
        constraints = [
            # Two partial constraints, not one unique_together(service, ars,
            # ars_program) -- Postgres treats NULL as distinct from NULL, so
            # a plain 3-field uniqueness would silently allow duplicate
            # ARS-level (ars_program=NULL) rows for the same service+ars.
            models.UniqueConstraint(
                fields=["service", "ars"],
                condition=models.Q(ars_program__isnull=True),
                name="uniq_serviceprice_ars_level",
            ),
            models.UniqueConstraint(
                fields=["service", "ars", "ars_program"],
                condition=models.Q(ars_program__isnull=False),
                name="uniq_serviceprice_ars_program_level",
            ),
        ]

    def __str__(self) -> str:
        scope = f"{self.ars.name} / {self.ars_program.name}" if self.ars_program_id else self.ars.name
        return f"{self.service.name} @ {scope}: {self.co_pago}"
