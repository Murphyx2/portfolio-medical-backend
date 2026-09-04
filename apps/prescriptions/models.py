import os
import uuid
from datetime import timedelta

from django.conf import settings
from django.db import models
from django.utils import timezone

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
    # Set once, in emitir() -- the moment BORRADOR -> EMITIDA actually
    # happened, distinct from `fecha` (a user-editable "prescription date")
    # and from `updated_at` (bumped by any save). This is the anchor the
    # 1-hour "Guardar cambios" edit window is measured against.
    emitida_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-fecha"]

    def __str__(self) -> str:
        return f"Receta #{self.pk} — {self.patient} ({self.get_estado_display()})"

    def is_locked_for_edit(self) -> bool:
        """The plain update/partial_update/destroy path (CanManageRecetas)
        only ever touches a BORRADOR -- once EMITIDA or ANULADA, mirrors
        Appointment/Encounter's own is_locked_for_edit() convention. An
        EMITIDA receta can still be amended within its 1-hour window, but
        only through the dedicated `guardar_cambios` action below, never the
        generic endpoint."""
        return self.estado != self.Estado.BORRADOR

    def editable_by_within_window(self, user) -> bool:
        """Gate for the `guardar_cambios` action (the 1-hour "fix a mistake
        without anular+duplicar" window): Admins may amend any EMITIDA
        receta at any time; the prescribing médico or the receta's creator
        may do so only within 1 hour of `emitida_at`. Never true for
        BORRADOR (use the plain update endpoint) or ANULADA (terminal)."""
        if self.estado != self.Estado.EMITIDA:
            return False
        if getattr(user, "is_admin", False):
            return True
        if self.emitida_at is None:
            return False
        if not (self.medico.user_id == user.id or self.created_by_id == user.id):
            return False
        return timezone.now() - self.emitida_at <= timedelta(hours=1)


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
