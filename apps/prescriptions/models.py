import os
import uuid

from django.conf import settings
from django.db import models

from apps.core.models import SoftDeleteModel, TimestampedModel


def receta_pdf_upload_to(instance, filename: str) -> str:
    # Randomize stored names: avoids enumerable URLs and user-controlled
    # names, same convention as records.models.record_image_upload_to.
    ext = os.path.splitext(filename)[1].lower()
    name = f"{uuid.uuid4().hex}{ext}"
    return f"recetas/{name}"


class Receta(TimestampedModel, SoftDeleteModel):
    """A prescription ("Receta médica"). PDF generation, the emitir/anular
    state-transition actions, and permission wiring beyond the placeholder
    IsAuthenticated gate on the ViewSet are a follow-up task -- this is the
    data-model layer only (RECETAS_REQUIREMENTS.md §2-5, §11)."""

    class Estado(models.TextChoices):
        BORRADOR = "BORRADOR", "Borrador"
        EMITIDA = "EMITIDA", "Emitida"
        ANULADA = "ANULADA", "Anulada"

    patient = models.ForeignKey(
        "patients.Patient",
        on_delete=models.CASCADE,
        related_name="recetas",
    )
    centro = models.ForeignKey(
        "centers.MedicalCenter",
        on_delete=models.CASCADE,
        related_name="recetas",
    )
    medico = models.ForeignKey(
        "doctors.DoctorProfile",
        on_delete=models.CASCADE,
        related_name="recetas",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="recetas_created",
    )
    fecha = models.DateTimeField()
    proxima_cita_at = models.DateTimeField(null=True, blank=True)
    cita = models.ForeignKey(
        "appointments.Appointment",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="recetas",
    )
    estado = models.CharField(max_length=10, choices=Estado.choices, default=Estado.BORRADOR)
    pdf = models.FileField(upload_to=receta_pdf_upload_to, null=True, blank=True)

    class Meta:
        ordering = ["-fecha"]

    def __str__(self) -> str:
        return f"Receta #{self.pk} — {self.patient} ({self.get_estado_display()})"


class RecetaLinea(models.Model):
    """One prescribed item on a Receta -- plain model, not Timestamped/
    SoftDelete, since lines are owned entirely by their parent Receta
    (same pattern as apps.doctors.models.DoctorPhoneNumber)."""

    receta = models.ForeignKey(Receta, on_delete=models.CASCADE, related_name="lineas")
    medicamento = models.ForeignKey(
        "medicines.Medicine",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    nombre_impreso = models.CharField(max_length=200)
    cantidad = models.DecimalField(max_digits=8, decimal_places=2)
    concentracion_valor = models.CharField(max_length=20, blank=True)
    unidad = models.CharField(max_length=10, blank=True)
    via = models.CharField(max_length=20, blank=True)
    forma = models.CharField(max_length=20, blank=True)
    fuera_de_catalogo = models.BooleanField(default=False)
    dosis_json = models.JSONField(default=dict, blank=True)
    dosis_texto = models.CharField(max_length=300, blank=True)
    indicacion_extra = models.CharField(max_length=300, blank=True)
    uso_continuo = models.BooleanField(default=False)
    orden = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["orden", "id"]

    def __str__(self) -> str:
        return f"{self.receta_id}:{self.nombre_impreso}"
