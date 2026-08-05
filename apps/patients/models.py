from django.db import models

from apps.core.fields import EncryptedCharField, EncryptedTextField
from apps.core.models import TimestampedModel


class Patient(TimestampedModel):
    """Patient records. Sensitive PII is stored encrypted at rest."""

    class Gender(models.TextChoices):
        MALE = "MALE", "Male"
        FEMALE = "FEMALE", "Female"
        OTHER = "OTHER", "Other"
        UNSPECIFIED = "UNSPECIFIED", "Unspecified"

    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100)
    birth_date = models.DateField(null=True, blank=True)
    gender = models.CharField(
        max_length=20,
        choices=Gender.choices,
        default=Gender.UNSPECIFIED,
    )

    # Encrypted PII at rest
    phone = EncryptedCharField(blank=True)
    address = EncryptedTextField(blank=True)
    email = EncryptedCharField(blank=True)

    # Read-only full name helper for display/search
    class Meta:
        ordering = ["last_name", "first_name"]
        indexes = [
            models.Index(fields=["last_name", "first_name"]),
        ]

    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}".strip()

    def __str__(self) -> str:
        return self.full_name
