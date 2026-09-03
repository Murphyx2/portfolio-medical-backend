import os
import uuid

from django.conf import settings
from django.db import models

from apps.core.models import SoftDeleteModel, TimestampedModel


def center_logo_upload_to(instance, filename: str) -> str:
    # Randomize stored names: avoids enumerable URLs and user-controlled
    # names, same convention as records.models.record_image_upload_to.
    ext = os.path.splitext(filename)[1].lower()
    name = f"{uuid.uuid4().hex}{ext}"
    return f"centers/{name}"


class MedicalCenter(TimestampedModel, SoftDeleteModel):
    name = models.CharField(max_length=200)
    code = models.CharField(max_length=20, unique=True)
    address = models.CharField(max_length=300)
    phone = models.CharField(max_length=30)
    email = models.EmailField(blank=True)
    # At most one center may be default -- enforced in save() below (same
    # invariant-in-save() convention as User.save() stripping is_staff on
    # role change), not just at the serializer/view layer.
    is_default = models.BooleanField(default=False)
    # Legal/billing identity fields for the prescription letterhead -- added
    # alongside the existing phone/email (kept for backward compatibility;
    # see MedicalCenterPhone/MedicalCenterEmail below for the repeatable
    # replacements, mirroring DoctorPhoneNumber's relationship to
    # DoctorProfile.contact_phone).
    rnc = models.CharField(max_length=20, blank=True)
    nombre_legal = models.CharField(max_length=200, blank=True)
    nombre_corto = models.CharField(max_length=50, blank=True)
    logo = models.ImageField(upload_to=center_logo_upload_to, null=True, blank=True)

    class Meta:
        ordering = ["name"]

    def save(self, *args, **kwargs):
        if self.is_default:
            MedicalCenter.objects.exclude(pk=self.pk).update(is_default=False)
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return self.name


class MedicalCenterPhone(models.Model):
    """Additional phone numbers beyond the legacy `MedicalCenter.phone`
    (kept for backward compatibility), same pattern as
    apps.doctors.models.DoctorPhoneNumber."""

    center = models.ForeignKey(MedicalCenter, on_delete=models.CASCADE, related_name="phones")
    number = models.CharField(max_length=30)
    order = models.PositiveSmallIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["order", "id"]

    def __str__(self) -> str:
        return f"{self.center_id}:{self.number}"


class MedicalCenterEmail(models.Model):
    """Additional emails beyond the legacy `MedicalCenter.email` (kept for
    backward compatibility), same pattern as MedicalCenterPhone above."""

    center = models.ForeignKey(MedicalCenter, on_delete=models.CASCADE, related_name="emails")
    email = models.EmailField()
    order = models.PositiveSmallIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["order", "id"]

    def __str__(self) -> str:
        return f"{self.center_id}:{self.email}"


class DoctorCenterBinding(TimestampedModel, SoftDeleteModel):
    """Binds a doctor to a medical center; access requires admin approval."""

    doctor = models.ForeignKey(
        "doctors.DoctorProfile",
        on_delete=models.CASCADE,
        related_name="center_bindings",
    )
    center = models.ForeignKey(
        MedicalCenter,
        on_delete=models.CASCADE,
        related_name="doctor_bindings",
    )
    approved = models.BooleanField(default=False)
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="approved_bindings",
    )

    class Meta:
        ordering = ["center", "doctor"]
        unique_together = ("doctor", "center")
        # user_accessible_center_ids() (apps/core/services.py) filters on
        # exactly this pair on every doctor-scoped request.
        indexes = [models.Index(fields=["doctor", "approved"])]

    def __str__(self) -> str:
        status = "approved" if self.approved else "pending"
        return f"{self.doctor} @ {self.center} ({status})"
