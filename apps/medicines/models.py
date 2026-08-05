from django.db import models

from apps.core.models import TimestampedModel


class Medicine(TimestampedModel):
    generic_name = models.CharField(
        max_length=200,
        verbose_name="Generic (medical) term",
    )
    commercial_name = models.CharField(max_length=200)
    concentration = models.CharField(max_length=100, blank=True)

    class Meta:
        ordering = ["generic_name", "commercial_name"]
        unique_together = ("generic_name", "commercial_name", "concentration")

    def __str__(self) -> str:
        base = f"{self.generic_name} ({self.commercial_name})"
        return f"{base} {self.concentration}".strip()
