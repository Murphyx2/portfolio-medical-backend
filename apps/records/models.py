import os
import uuid

from django.conf import settings
from django.db import models

from apps.core.fields import EncryptedTextField
from apps.core.models import SoftDeleteModel, TimestampedModel


class MedicalRecord(TimestampedModel, SoftDeleteModel):
    """Doctor-written medical record with encrypted clinical content."""

    patient = models.ForeignKey(
        "patients.Patient",
        on_delete=models.CASCADE,
        related_name="medical_records",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="authored_records",
    )
    center = models.ForeignKey(
        "centers.MedicalCenter",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="medical_records",
    )
    title = models.CharField(max_length=200)
    date = models.DateTimeField(auto_now_add=True)

    diagnosis = EncryptedTextField(blank=True)
    treatment = EncryptedTextField(blank=True)
    medicine_and_doses = EncryptedTextField(blank=True)
    notes = EncryptedTextField(blank=True)

    class Meta:
        ordering = ["-date"]
        indexes = [
            models.Index(fields=["-date"], name="records_mr_date_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.title} — {self.patient.full_name}"


class ConsultationLog(TimestampedModel, SoftDeleteModel):
    """A log of what happened during a consultation (SOAP-style notes)."""

    patient = models.ForeignKey(
        "patients.Patient",
        on_delete=models.CASCADE,
        related_name="consultation_logs",
    )
    doctor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="consultation_logs",
    )
    center = models.ForeignKey(
        "centers.MedicalCenter",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="consultation_logs",
    )
    date = models.DateTimeField(auto_now_add=True)

    subjective = EncryptedTextField(blank=True)
    objective = EncryptedTextField(blank=True)
    assessment = EncryptedTextField(blank=True)
    plan = EncryptedTextField(blank=True)
    notes = EncryptedTextField(blank=True)

    class Meta:
        ordering = ["-date"]
        indexes = [
            models.Index(fields=["-date"], name="records_cl_date_idx"),
        ]

    def __str__(self) -> str:
        return f"Log {self.patient.full_name} {self.date:%Y-%m-%d}"


def record_image_upload_to(instance, filename: str) -> str:
    # Randomize stored names: avoids enumerable URLs and user-controlled names.
    ext = os.path.splitext(filename)[1].lower()
    name = f"{uuid.uuid4().hex}{ext}"
    return f"records/{instance.record.patient_id}/{name}"


class RecordImage(TimestampedModel, SoftDeleteModel):
    record = models.ForeignKey(
        MedicalRecord,
        on_delete=models.CASCADE,
        related_name="images",
    )
    image = models.ImageField(upload_to=record_image_upload_to)
    caption = models.CharField(max_length=255, blank=True)
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="uploaded_record_images",
    )

    def __str__(self) -> str:
        return self.caption or self.image.name


class APCategory(TimestampedModel, SoftDeleteModel):
    """A category in the AP (Antecedentes Patológicos / pathological
    history) catalog -- mirrors apps.services.ServiceType's category role."""

    name = models.CharField(max_length=255, unique=True)
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["sort_order", "name"]

    def __str__(self) -> str:
        return self.name


class APType(TimestampedModel, SoftDeleteModel):
    """A selectable item in the AP catalog under a category -- mirrors
    apps.services.Service's item role. PROTECT on category so a category
    with items on file can't be hard-deleted out from under them."""

    category = models.ForeignKey(APCategory, on_delete=models.PROTECT, related_name="types")
    name = models.CharField(max_length=255)
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["sort_order", "name"]
        constraints = [
            models.UniqueConstraint(
                fields=["category", "name"],
                condition=models.Q(active=True),
                name="uniq_active_aptype_category_name",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.name} ({self.category.name})"
