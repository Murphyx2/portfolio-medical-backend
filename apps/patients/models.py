from django.db import models

from apps.core.encryption import blind_index_digits
from apps.core.fields import EncryptedCharField, EncryptedTextField
from apps.core.models import SoftDeleteModel, TimestampedModel


class Patient(TimestampedModel, SoftDeleteModel):
    """Patient records. Sensitive PII is stored encrypted at rest."""

    class Gender(models.TextChoices):
        MALE = "MALE", "Male"
        FEMALE = "FEMALE", "Female"
        OTHER = "OTHER", "Other"
        UNSPECIFIED = "UNSPECIFIED", "Unspecified"

    # Names/birth date are PII too: encrypted at rest. A plaintext lowercase
    # `search_name` index column keeps name search working (documented tradeoff).
    first_name = EncryptedCharField()
    last_name = EncryptedCharField()
    birth_date = EncryptedCharField(null=True, blank=True)
    search_name = models.CharField(max_length=201, blank=True)
    gender = models.CharField(
        max_length=20,
        choices=Gender.choices,
        default=Gender.UNSPECIFIED,
    )

    # Encrypted PII at rest
    phone = EncryptedCharField(blank=True)
    address = EncryptedTextField(blank=True)
    email = EncryptedCharField(blank=True)
    cedula = EncryptedCharField()
    nss = EncryptedCharField(blank=True)

    # Plaintext last-4-digit index of cedula/NSS (same documented tradeoff as
    # `search_name`): digit searches match in SQL against these columns instead
    # of decrypting every row in Python (M-01).
    cedula_last4 = models.CharField(max_length=4, blank=True, db_index=True)
    nss_last4 = models.CharField(max_length=4, blank=True, db_index=True)

    # Keyed-hash (blind index) of the *complete* cedula/NSS digits, so a
    # full-number search can match exactly instead of via the last-4 index
    # (which can false-positive across patients sharing the same tail). The
    # number is never decrypted to compute or query this -- same "no
    # decryption in the search path" property as cedula_last4/nss_last4.
    cedula_hash = models.CharField(max_length=64, blank=True, db_index=True)
    nss_hash = models.CharField(max_length=64, blank=True, db_index=True)

    # Center where the patient is registered (null = unbound/visible to all staff).
    center = models.ForeignKey(
        "centers.MedicalCenter",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="patients",
    )

    # Insurance (ARS) binding
    ars = models.ForeignKey(
        "ars.ARS",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="patients",
    )
    ars_program = models.ForeignKey(
        "ars.ARSProgram",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="patients",
    )

    class Meta:
        ordering = ["search_name"]
        indexes = [
            models.Index(fields=["search_name"]),
        ]
        constraints = [
            # A cedula/NSS must match exactly one patient. Scoped to active
            # rows -- soft-deleting a patient (apps/core/mixins.py) frees
            # their cedula/NSS for reuse, matching the SoftDeleteModel
            # convention used everywhere else in this codebase. NSS is
            # optional, so its constraint additionally excludes the blank
            # (no-NSS) case.
            models.UniqueConstraint(
                fields=["cedula_hash"],
                condition=models.Q(active=True) & ~models.Q(cedula_hash=""),
                name="uniq_active_patient_cedula_hash",
            ),
            models.UniqueConstraint(
                fields=["nss_hash"],
                condition=models.Q(active=True) & ~models.Q(nss_hash=""),
                name="uniq_active_patient_nss_hash",
            ),
        ]

    def save(self, *args, **kwargs):
        self.search_name = f"{self.first_name or ''} {self.last_name or ''}".strip().lower()
        self.cedula_last4 = (self.cedula or "")[-4:]
        self.nss_last4 = (self.nss or "")[-4:]
        self.cedula_hash = blind_index_digits(self.cedula)
        self.nss_hash = blind_index_digits(self.nss)
        super().save(*args, **kwargs)

    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}".strip()

    def __str__(self) -> str:
        return self.full_name
