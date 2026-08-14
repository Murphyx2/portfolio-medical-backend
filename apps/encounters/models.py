from django.conf import settings
from django.db import models
from django.utils import timezone

from apps.core.models import SoftDeleteModel, TimestampedModel


class EncounterType(TimestampedModel, SoftDeleteModel):
    name = models.CharField(max_length=255, unique=True)
    # Some encounter types (e.g. a routine vitals-only visit) don't require a
    # primary diagnosis before admission -- see Encounter.ready_for_active().
    requires_diagnosis = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class Encounter(TimestampedModel, SoftDeleteModel):
    class Status(models.TextChoices):
        DRAFT = "DRAFT", "Draft"
        ACTIVE = "ACTIVE", "Active"
        COMPLETED = "COMPLETED", "Completed"
        CANCELLED = "CANCELLED", "Cancelled"

    class Priority(models.TextChoices):
        ROUTINE = "ROUTINE", "Routine"
        URGENT = "URGENT", "Urgent"
        EMERGENCY = "EMERGENCY", "Emergency"

    # Blank/null until admit() assigns it -- a DRAFT encounter has no number
    # yet. Nullable (not just blank) so the uniqueness constraint only
    # applies once a number is actually assigned (multiple NULLs don't
    # collide under a unique index).
    encounter_number = models.CharField(max_length=40, unique=True, null=True, blank=True)
    encounter_type = models.ForeignKey(
        EncounterType, on_delete=models.PROTECT, related_name="encounters"
    )
    patient = models.ForeignKey(
        "patients.Patient", on_delete=models.PROTECT, related_name="encounters"
    )
    doctor = models.ForeignKey(
        "doctors.DoctorProfile", on_delete=models.PROTECT, related_name="encounters"
    )
    # Free text for now -- full referral routing/cross-center workflow is
    # deferred; this just records who referred the patient, if anyone.
    referring_doctor_name = models.CharField(max_length=200, blank=True)
    # Nullable: required only once the encounter goes ACTIVE (see
    # ready_for_active()), not while still a DRAFT.
    room = models.ForeignKey(
        "rooms.Room",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="encounters",
    )
    center = models.ForeignKey(
        "centers.MedicalCenter",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="encounters",
    )
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT)
    priority = models.CharField(
        max_length=20, choices=Priority.choices, default=Priority.ROUTINE
    )
    admitted_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    # Free-text clinical fields: masked in the serializer for non-clinical
    # roles (same convention as MedicalRecord.diagnosis/ConsultationLog),
    # not encrypted at rest -- matches the existing records app precedent.
    chief_complaint = models.TextField(blank=True)
    cancel_reason = models.CharField(max_length=255, blank=True)

    # Coverage
    ars = models.ForeignKey(
        "ars.ARS", on_delete=models.PROTECT, null=True, blank=True, related_name="encounters"
    )
    ars_program = models.ForeignKey(
        "ars.ARSProgram",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="encounters",
    )
    authorization_number = models.CharField(max_length=100, blank=True)

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="created_encounters"
    )

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["patient", "status"]),
            models.Index(fields=["status", "created_at"]),
        ]

    def ready_for_active(self) -> list[str]:
        """Field-level gaps that block DRAFT -> ACTIVE. Empty list = ready.

        Does not check the same-day-active-encounter conflict -- that needs
        a query against sibling encounters, done separately by the admit
        view (apps/encounters/views.py) so this stays a pure, query-free
        check reusable from serializer validation too.
        """
        errors = []
        if self.room_id is None:
            errors.append("A room is required to admit this encounter.")
        if self.encounter_type_id and self.encounter_type.requires_diagnosis:
            if not self.diagnoses.filter(is_primary=True).exists():
                errors.append("A primary diagnosis is required to admit this encounter.")
        return errors

    def __str__(self) -> str:
        return self.encounter_number or f"Encounter #{self.pk} ({self.patient.full_name})"


class EncounterDiagnosis(TimestampedModel):
    encounter = models.ForeignKey(Encounter, on_delete=models.CASCADE, related_name="diagnoses")
    description = models.TextField()
    is_primary = models.BooleanField(default=False)

    class Meta:
        ordering = ["-is_primary", "id"]

    def __str__(self) -> str:
        return self.description[:50]


class EncounterService(TimestampedModel):
    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending"
        COMPLETED = "COMPLETED", "Completed"
        CANCELLED = "CANCELLED", "Cancelled"

    encounter = models.ForeignKey(Encounter, on_delete=models.CASCADE, related_name="services")
    service = models.ForeignKey(
        "services.Service", on_delete=models.PROTECT, related_name="encounter_services"
    )
    doctor = models.ForeignKey(
        "doctors.DoctorProfile",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="encounter_services",
    )
    quantity = models.PositiveIntegerField(default=1)
    notes = models.TextField(blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)

    class Meta:
        ordering = ["id"]

    def __str__(self) -> str:
        return f"{self.service.name} x{self.quantity}"


def generate_encounter_number(encounter: Encounter, *, today=None) -> str:
    """`ENC-{center_code|GEN}-{YYYYMMDD}-{seq:04d}`, retrying on a collision.

    No reservation table for the per-day sequence -- this optimistically
    tries the next candidate and lets the DB's unique constraint on
    `encounter_number` catch a race, retrying with seq+1 on IntegrityError
    (same optimistic-retry shape as the cedula/NSS blind-index uniqueness
    check, just against a real DB constraint instead of a pre-check query).
    """
    from django.db import IntegrityError, transaction

    today = today or timezone.localdate()
    prefix = f"ENC-{encounter.center.code if encounter.center_id else 'GEN'}-{today:%Y%m%d}"
    seq = Encounter.all_objects.filter(encounter_number__startswith=f"{prefix}-").count() + 1
    while True:
        candidate = f"{prefix}-{seq:04d}"
        try:
            with transaction.atomic():
                Encounter.all_objects.filter(pk=encounter.pk).update(
                    encounter_number=candidate
                )
            return candidate
        except IntegrityError:
            seq += 1
