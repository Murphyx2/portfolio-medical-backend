from datetime import date

from django.db import models

from apps.core.encryption import blind_index_digits
from apps.core.fields import EncryptedCharField, EncryptedTextField
from apps.core.models import SoftDeleteModel, TimestampedModel


def patient_age(patient_or_birth_date) -> int | None:
    """Age in years from a birth date; None when absent/unparseable.

    Accepts either a `Patient` instance (reads its `birth_date`) or a raw
    birth-date value (str/date) directly, so callers validating incoming
    request data (which isn't a saved instance yet) can reuse the same
    arithmetic as callers reading an existing row.
    """
    bd = getattr(patient_or_birth_date, "birth_date", patient_or_birth_date)
    if not bd:
        return None
    if isinstance(bd, str):
        try:
            bd = date.fromisoformat(bd)
        except ValueError:
            return None
    today = date.today()
    return (
        today.year
        - bd.year
        - ((today.month, today.day) < (bd.month, bd.day))
    )


class Patient(TimestampedModel, SoftDeleteModel):
    """Patient records. Sensitive PII is stored encrypted at rest."""

    class Gender(models.TextChoices):
        MALE = "MALE", "Male"
        FEMALE = "FEMALE", "Female"

    # Names/birth date are PII too: encrypted at rest. A plaintext lowercase
    # `search_name` index column keeps name search working (documented tradeoff).
    first_name = EncryptedCharField()
    last_name = EncryptedCharField()
    birth_date = EncryptedCharField()
    search_name = models.CharField(max_length=201, blank=True)
    # No default -- gender is mandatory, same as cedula/birth_date (no
    # blank=True/null=True/default means DRF's automatic field generation
    # marks it required with no silently-applied value).
    gender = models.CharField(
        max_length=20,
        choices=Gender.choices,
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

    # Whether guardian/parent info is collected for this (minor) patient at
    # all -- see PatientSerializer.validate for the conditional-required
    # rule. The guardians themselves live in the related PatientGuardian
    # model (a patient can have more than one on file).
    has_guardian = models.BooleanField(default=True)

    # Persistent clinical safety flags (not per-visit) so the encounter
    # summary card can show them with an O(1) lookup instead of scanning
    # medical record history.
    allergies = EncryptedTextField(blank=True, default="")
    critical_conditions = EncryptedTextField(blank=True, default="")

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

    # Single source of truth for "encrypted field -> derived plaintext index
    # column(s)". Consumed by save() below and by
    # apps.core.management.commands.reencrypt_pii, so a new helper column
    # only needs one entry here instead of being wired up in both places
    # separately (the latter used to be a hard-coded tuple that silently
    # missed guardian_cedula_hash on key rotation).
    PII_INDEX_FIELDS = {
        "cedula": ("cedula_last4", "cedula_hash"),
        "nss": ("nss_last4", "nss_hash"),
    }

    def _derive_pii_indexes(self):
        for source, (last4_field, hash_field) in self.PII_INDEX_FIELDS.items():
            value = getattr(self, source, "") or ""
            if last4_field:
                setattr(self, last4_field, value[-4:])
            if hash_field:
                setattr(self, hash_field, blind_index_digits(value))

    def save(self, *args, **kwargs):
        self.search_name = f"{self.first_name or ''} {self.last_name or ''}".strip().lower()
        self._derive_pii_indexes()
        super().save(*args, **kwargs)

    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}".strip()

    @property
    def primary_guardian(self) -> "PatientGuardian | None":
        """First guardian on file, if any. Exists only so serializers that
        used to expose a single flat guardian_* field set (encounters'
        nested PatientSummarySerializer, the Encounters/Patients frontend)
        keep working unchanged after guardians became a list -- new code
        should read `.guardians.all()` directly instead.

        Deliberately `.all()` rather than `.order_by("id").first()`: this
        model's default ordering is already `["id"]`, and `.all()` is the
        form that reuses a `prefetch_related("guardians")` cache -- any
        further queryset method (including a redundant `.order_by()`) forces
        a fresh query per call, silently reintroducing the N+1 this
        property's callers rely on the caller's prefetch to avoid.
        """
        guardians = list(self.guardians.all())
        return guardians[0] if guardians else None

    def __str__(self) -> str:
        return self.full_name


class PatientGuardian(TimestampedModel):
    """A parent/tutor on file for a (usually minor) patient. A patient may
    have more than one (e.g. both parents) -- see PatientSerializer.validate
    for the conditional-required rule this backs."""

    patient = models.ForeignKey(
        Patient, on_delete=models.CASCADE, related_name="guardians"
    )
    first_name = EncryptedCharField()
    last_name = EncryptedCharField()
    cedula = EncryptedCharField(blank=True, default="")
    nss = EncryptedCharField(blank=True, default="")
    phone = EncryptedCharField(blank=True, default="")

    # Same last4/blind-hash search index as Patient.cedula_last4/cedula_hash,
    # so front-desk staff can find a minor by the only ID they may have on
    # hand: the guardian's. Deliberately NOT unique -- siblings can share a
    # guardian, and matching several patients on the same guardian cedula is
    # the intended behavior.
    cedula_last4 = models.CharField(max_length=4, blank=True, db_index=True)
    cedula_hash = models.CharField(max_length=64, blank=True, db_index=True)

    PII_INDEX_FIELDS = {
        "cedula": ("cedula_last4", "cedula_hash"),
    }

    class Meta:
        ordering = ["id"]

    def _derive_pii_indexes(self):
        for source, (last4_field, hash_field) in self.PII_INDEX_FIELDS.items():
            value = getattr(self, source, "") or ""
            if last4_field:
                setattr(self, last4_field, value[-4:])
            if hash_field:
                setattr(self, hash_field, blind_index_digits(value))

    def save(self, *args, **kwargs):
        self._derive_pii_indexes()
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"{self.patient_id}:{self.first_name} {self.last_name}".strip()


class PatientPhoneNumber(models.Model):
    """Additional phone numbers beyond `Patient.phone` (the primary number,
    left untouched everywhere it's already read -- masking, the Appointments
    "patient phone" column, etc). Encrypted like every other patient PII
    field."""

    patient = models.ForeignKey(
        Patient, on_delete=models.CASCADE, related_name="extra_phones"
    )
    phone = EncryptedCharField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["id"]

    def __str__(self) -> str:
        return f"{self.patient_id}:{self.phone}"
