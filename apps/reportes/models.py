from django.db import models

from apps.core.models import TimestampedModel

# Closed choice lists: a definition/pack can only ever point at an engine
# this app actually implements -- there is no "type any view name" catalog
# (Requirements/ReportPage/REPORTES_REQUIREMENTS.md section 7).
REPORT_ENGINE_CHOICES = [("servicios_prestados", "Servicios prestados")]
PACK_ENGINE_CHOICES = [("paquete_ars", "Paquete ARS")]


class ReportDefinition(TimestampedModel):
    name = models.CharField(max_length=200)
    category = models.CharField(max_length=100)
    description = models.CharField(max_length=300, blank=True)
    engine_key = models.CharField(max_length=50, choices=REPORT_ENGINE_CHOICES)
    active = models.BooleanField(default=True)
    last_generated_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class ReportPack(TimestampedModel):
    name = models.CharField(max_length=200)
    periodicity = models.CharField(max_length=50, default="MENSUAL")
    engine_key = models.CharField(max_length=50, choices=PACK_ENGINE_CHOICES)
    active = models.BooleanField(default=True)
    last_generated_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name
