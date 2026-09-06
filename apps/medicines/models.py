from django.db import models

from apps.core.models import SoftDeleteModel, TimestampedModel


class Medicine(TimestampedModel, SoftDeleteModel):
    class Forma(models.TextChoices):
        TABLETA = "TABLETA", "Tableta"
        CAPSULA = "CAPSULA", "Cápsula"
        JARABE = "JARABE", "Jarabe"
        GOTAS = "GOTAS", "Gotas"
        CREMA = "CREMA", "Crema"
        UNGUENTO = "UNGUENTO", "Ungüento"
        AMPOLLA = "AMPOLLA", "Ampolla"
        VIAL = "VIAL", "Vial"
        INHALADOR = "INHALADOR", "Inhalador"
        PARCHE = "PARCHE", "Parche"
        SUSPENSION = "SUSPENSION", "Suspensión"
        SUPOSITORIO = "SUPOSITORIO", "Supositorio"
        OTRO = "OTRO", "Otro"

    class ViaAdministracion(models.TextChoices):
        ORAL = "ORAL", "Oral"
        SUBLINGUAL = "SUBLINGUAL", "Sublingual"
        SC = "SC", "SC"
        IM = "IM", "IM"
        IV = "IV", "IV"
        TOPICA = "TOPICA", "Tópica"
        OFTALMICA = "OFTALMICA", "Oftálmica"
        OTICA = "OTICA", "Ótica"
        NASAL = "NASAL", "Nasal"
        INHALATORIA = "INHALATORIA", "Inhalatoria"
        RECTAL = "RECTAL", "Rectal"
        OTRO = "OTRO", "Otro"

    class ConcentracionUnidad(models.TextChoices):
        MG = "mg", "mg"
        MCG = "mcg", "mcg"
        G = "g", "g"
        ML = "ml", "ml"
        UI = "UI", "UI"
        UI_ML = "UI/ml", "UI/ml"
        PORCENTAJE = "%", "%"
        MG_ML = "mg/ml", "mg/ml"
        OTRO = "OTRO", "Otro"

    generic_name = models.CharField(
        max_length=200,
        verbose_name="Generic (medical) term",
    )
    commercial_name = models.CharField(max_length=200)
    concentration = models.CharField(max_length=100, blank=True)
    forma = models.CharField(max_length=20, choices=Forma.choices, blank=True)
    via_pred = models.CharField(max_length=20, choices=ViaAdministracion.choices, blank=True)
    # Structured concentration (valor+unidad) alongside the legacy free-text
    # `concentration` field, which save() below keeps in sync -- see
    # RECETAS_REQUIREMENTS.md §3. concentracion_valor stays a CharField
    # (numeric-as-text is fine, matches the free-text nature of doses
    # elsewhere in this codebase) rather than a DecimalField.
    concentracion_valor = models.CharField(max_length=20, blank=True)
    concentracion_unidad = models.CharField(max_length=10, choices=ConcentracionUnidad.choices, blank=True)
    concentracion_unidad_otro = models.CharField(max_length=20, blank=True)

    class Meta:
        ordering = ["generic_name", "commercial_name"]
        unique_together = ("generic_name", "commercial_name", "concentration")

    def save(self, *args, **kwargs):
        # Keep the legacy free-text `concentration` field in sync whenever
        # the structured fields are actually populated -- only when
        # concentracion_valor is set, so existing free-text concentration
        # values with no structured equivalent yet are never clobbered.
        if self.concentracion_valor and self.concentracion_unidad:
            self.concentration = f"{self.concentracion_valor}{self.concentracion_unidad}"
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        base = f"{self.generic_name} ({self.commercial_name})"
        return f"{base} {self.concentration}".strip()
