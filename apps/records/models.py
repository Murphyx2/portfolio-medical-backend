from django.conf import settings
from django.db import models

from apps.core.fields import EncryptedTextField
from apps.core.models import TimestampedModel


class MedicalRecord(TimestampedModel):
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

    def __str__(self) -> str:
        return f"{self.title} — {self.patient.full_name}"


class ConsultationLog(TimestampedModel):
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

    def __str__(self) -> str:
        return f"Log {self.patient.full_name} {self.date:%Y-%m-%d}"


def record_image_upload_to(instance, filename: str) -> str:
    return f"records/{instance.record.patient_id}/{filename}"


class RecordImage(TimestampedModel):
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
