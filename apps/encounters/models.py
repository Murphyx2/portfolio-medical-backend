from django.conf import settings
from django.db import models, transaction
from django.utils import timezone

from apps.core.models import SoftDeleteModel, TimestampedModel


class EncounterAdmitError(Exception):
    """Raised by Encounter.admit() on any failure to transition DRAFT ->
    ACTIVE. ``detail`` mirrors what the view's ValidationError response
    body carries (a string or list of strings); ``code`` is set only for
    the same-day-active-conflict case (ACTIVE_ENCOUNTER_EXISTS), matching
    the response shape the frontend and tests already expect."""

    def __init__(self, detail, *, code: str | None = None):
        self.detail = detail
        self.code = code
        super().__init__(detail if isinstance(detail, str) else str(detail))


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
    # Same catalog Services are categorized under (apps/services.ServiceType)
    # -- selecting one narrows the Services section to that type's services,
    # and its requires_doctor/requires_diagnosis flags drive the doctor and
    # admit-time diagnosis requirements below.
    service_type = models.ForeignKey(
        "services.ServiceType", on_delete=models.PROTECT, related_name="encounters"
    )
    patient = models.ForeignKey(
        "patients.Patient", on_delete=models.PROTECT, related_name="encounters"
    )
    # Nullable: only required when service_type.requires_doctor is true (see
    # EncounterSerializer.validate()) -- not every service needs a doctor
    # present (e.g. a lab-only visit).
    doctor = models.ForeignKey(
        "doctors.DoctorProfile",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="encounters",
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
            models.Index(fields=["created_at"]),
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
        return errors

    def admit(self, *, override_conflict: bool = False) -> None:
        """Transition DRAFT -> ACTIVE: validates readiness, checks for a
        same-day active-encounter conflict (bypassable via
        ``override_conflict``), assigns the encounter number, and persists
        the transition -- all atomically. Raises EncounterAdmitError on any
        failure; the view translates that into the ValidationError response
        shape callers already depend on (``{"detail": ...}`` or
        ``{"code": "ACTIVE_ENCOUNTER_EXISTS", "detail": ...}``).

        Uses ``Encounter.all_objects`` for the conflict query (not the
        soft-delete-default manager) to match the ViewSet's own queryset
        semantics -- a soft-deleted ACTIVE encounter should still count as
        a same-day conflict, same as it still counts everywhere else the
        ViewSet reads/writes this model.
        """
        if self.status != Encounter.Status.DRAFT:
            raise EncounterAdmitError("Only a draft encounter can be admitted.")
        errors = self.ready_for_active()
        if errors:
            raise EncounterAdmitError(errors)

        today = timezone.localdate()
        conflict = (
            Encounter.all_objects.filter(
                patient=self.patient,
                status=Encounter.Status.ACTIVE,
                admitted_at__date=today,
            )
            .exclude(pk=self.pk)
            .exists()
        )
        if conflict and not override_conflict:
            raise EncounterAdmitError(
                "This patient already has an active encounter today.",
                code="ACTIVE_ENCOUNTER_EXISTS",
            )

        with transaction.atomic():
            self.status = Encounter.Status.ACTIVE
            self.admitted_at = timezone.now()
            self.save(update_fields=["status", "admitted_at"])
            generate_encounter_number(self, today=today)
        self.refresh_from_db()

    def has_completed_service(self) -> bool:
        return self.services.filter(status="COMPLETED").exists()

    def is_locked_for_edit(self) -> bool:
        """True once the encounter (or any of its service lines) has
        reached a terminal/billed state that must not be rewritten after
        the fact. Non-admin write access is blocked once this is True (see
        apps.core.permissions.CanManageEncounters)."""
        return self.status in ("COMPLETED", "CANCELLED") or self.has_completed_service()

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
    """`{YYYYMMDD}-{seq:03d}`, retrying on a collision.

    The sequence is a clinic-wide daily count of admitted patients (not
    scoped per center), matching how front-desk staff think of "the Nth
    admission today". No reservation table for it -- this optimistically
    tries the next candidate and lets the DB's unique constraint on
    `encounter_number` catch a race, retrying with seq+1 on IntegrityError
    (same optimistic-retry shape as the cedula/NSS blind-index uniqueness
    check, just against a real DB constraint instead of a pre-check query).
    """
    from django.db import IntegrityError, transaction

    today = today or timezone.localdate()
    prefix = f"{today:%Y%m%d}"
    seq = Encounter.all_objects.filter(encounter_number__startswith=f"{prefix}-").count() + 1
    while True:
        candidate = f"{prefix}-{seq:03d}"
        try:
            with transaction.atomic():
                Encounter.all_objects.filter(pk=encounter.pk).update(
                    encounter_number=candidate
                )
            return candidate
        except IntegrityError:
            seq += 1
