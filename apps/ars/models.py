from django.db import models

from apps.core.models import TimestampedModel


class ARS(TimestampedModel):
    """ARS insurance company (Aseguradora de Salud)."""

    ars_id = models.CharField(max_length=20, unique=True, verbose_name="ARS ID")
    name = models.CharField(max_length=200, unique=True)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class ARSProgram(TimestampedModel):
    """A program an ARS offers to its customers."""

    ars = models.ForeignKey(
        ARS,
        on_delete=models.CASCADE,
        related_name="programs",
    )
    name = models.CharField(max_length=200)

    class Meta:
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(
                fields=["ars", "name"],
                name="uniq_ars_program_name",
            ),
        ]

    def __str__(self) -> str:
        return self.name
