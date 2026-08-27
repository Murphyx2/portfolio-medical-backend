import os
import uuid

from django.conf import settings
from django.db import models

from apps.core.fields import EncryptedTextField
from apps.core.models import SoftDeleteModel, TimestampedModel


class MedicalRecord(TimestampedModel, SoftDeleteModel):
    """The living clinical chart ("Expediente Médico") anchor -- one per
    active patient (see the uniq_active_medicalrecord_patient constraint).
    Carries no clinical content of its own; every visit's Dx/Tx/Observaciones
    and vitals live on its RecordEntry children (see RecordEntry.complete()),
    and the fields below cache each vital's most recent *valid* value plus
    the date it was taken, so the patient-snapshot header never has to scan
    history to render "Última TA", "Último peso", etc.
    """

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

    last_visit_at = models.DateTimeField(null=True, blank=True)
    last_height_cm = models.DecimalField(max_digits=5, decimal_places=1, null=True, blank=True)
    last_height_at = models.DateTimeField(null=True, blank=True)
    last_weight_lb = models.DecimalField(max_digits=6, decimal_places=1, null=True, blank=True)
    last_weight_at = models.DateTimeField(null=True, blank=True)
    last_imc = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    last_imc_at = models.DateTimeField(null=True, blank=True)
    last_ta_systolic = models.PositiveSmallIntegerField(null=True, blank=True)
    last_ta_diastolic = models.PositiveSmallIntegerField(null=True, blank=True)
    last_ta_at = models.DateTimeField(null=True, blank=True)
    last_fc = models.PositiveSmallIntegerField(null=True, blank=True)
    last_fc_at = models.DateTimeField(null=True, blank=True)
    last_fr = models.PositiveSmallIntegerField(null=True, blank=True)
    last_fr_at = models.DateTimeField(null=True, blank=True)
    last_glucose = models.PositiveSmallIntegerField(null=True, blank=True)
    last_glucose_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-last_visit_at", "-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["patient"],
                condition=models.Q(active=True),
                name="uniq_active_medicalrecord_patient",
            ),
        ]
        indexes = [
            models.Index(fields=["-last_visit_at"], name="records_mr_last_visit_idx"),
        ]

    def __str__(self) -> str:
        return f"Expediente — {self.patient.full_name}"


class RecordEntry(TimestampedModel):
    """One clinical visit against a MedicalRecord: draft (auto-saved,
    private to its author) or completed (append-only, part of Historial).
    See RecordEntry.complete() for the transactional last-* recompute and
    AP-snapshot logic that runs when a draft becomes completed."""

    class Status(models.TextChoices):
        DRAFT = "DRAFT", "Draft"
        COMPLETED = "COMPLETED", "Completed"

    record = models.ForeignKey(MedicalRecord, on_delete=models.CASCADE, related_name="entries")
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="record_entries"
    )
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.DRAFT)

    ta_systolic = models.PositiveSmallIntegerField(null=True, blank=True)
    ta_diastolic = models.PositiveSmallIntegerField(null=True, blank=True)
    fc = models.PositiveSmallIntegerField(null=True, blank=True)
    fr = models.PositiveSmallIntegerField(null=True, blank=True)
    weight_lb = models.DecimalField(max_digits=6, decimal_places=1, null=True, blank=True)
    height_cm = models.DecimalField(max_digits=5, decimal_places=1, null=True, blank=True)
    talla_cm = models.DecimalField(max_digits=5, decimal_places=1, null=True, blank=True)
    temperature_c = models.DecimalField(max_digits=4, decimal_places=1, null=True, blank=True)
    glucose = models.PositiveSmallIntegerField(null=True, blank=True)
    vitals_notes = models.CharField(max_length=500, blank=True, default="")
    imc = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)

    dx = EncryptedTextField(blank=True, default="")
    tx = EncryptedTextField(blank=True, default="")
    observaciones = EncryptedTextField(blank=True, default="")

    # Frozen at complete() time: [{ap_type_id, label, is_custom}, ...] and
    # [{related_patient_id, relationship, relationship_other, relative_name,
    # ap_type_id, label, is_custom}, ...] respectively. Read-only history --
    # never mutated after an entry completes, even if the living
    # RecordPersonalCondition/RecordFamilyCondition rows change later.
    personal_ap_snapshot = models.JSONField(default=list, blank=True)
    family_ap_snapshot = models.JSONField(default=list, blank=True)

    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-completed_at", "-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["record", "author"],
                condition=models.Q(status="DRAFT"),
                name="uniq_draft_per_record_author",
            ),
        ]
        indexes = [
            models.Index(fields=["record", "status", "-completed_at"], name="records_entry_status_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.get_status_display()} entry — {self.record.patient.full_name}"

    def has_clinical_content(self) -> bool:
        """Spec §11: a completed save with every clinical field empty is
        blocked ("No hay cambios para guardar") -- checked before complete()
        commits anything."""
        return bool(
            self.ta_systolic
            or self.ta_diastolic
            or self.fc
            or self.fr
            or self.weight_lb
            or self.height_cm
            or self.talla_cm
            or self.temperature_c
            or self.glucose
            or self.vitals_notes
            or self.dx
            or self.tx
            or self.observaciones
            or self.record.personal_conditions.exists()
            or self.record.family_conditions.exists()
        )

    def complete(self, actor):
        """Transactionally: validate there's something to save, recompute
        the parent MedicalRecord's last-* cache (only for fields this entry
        actually supplies a non-empty value for -- clearing a field before
        Guardar must never blank out a previously recorded "último"), freeze
        the current living AP state into this entry's snapshot columns, and
        mark this entry COMPLETED. Raises ValueError (mapped to a 400 by the
        view) when there's nothing to save.

        Also doubles as the "Editar última entrada" resave path -- called
        again on an already-COMPLETED entry -- in which case the original
        author/completed_at are preserved (spec: "Observations keep their
        original author and timestamp") and only the content and the
        last-* recompute apply.
        """
        from django.db import transaction
        from django.utils import timezone

        from apps.records.services import compute_imc

        with transaction.atomic():
            record = MedicalRecord.objects.select_for_update().get(pk=self.record_id)
            if not self.has_clinical_content():
                raise ValueError("NO_CHANGES")

            was_draft = self.status == self.Status.DRAFT
            now = timezone.now()
            if self.ta_systolic and self.ta_diastolic:
                record.last_ta_systolic = self.ta_systolic
                record.last_ta_diastolic = self.ta_diastolic
                record.last_ta_at = now
            if self.fc:
                record.last_fc = self.fc
                record.last_fc_at = now
            if self.fr:
                record.last_fr = self.fr
                record.last_fr_at = now
            if self.glucose:
                record.last_glucose = self.glucose
                record.last_glucose_at = now
            if self.height_cm:
                record.last_height_cm = self.height_cm
                record.last_height_at = now
            if self.weight_lb:
                record.last_weight_lb = self.weight_lb
                record.last_weight_at = now
            if self.height_cm or self.weight_lb:
                height_cm = self.height_cm or record.last_height_cm
                weight_lb = self.weight_lb or record.last_weight_lb
                if height_cm and weight_lb:
                    imc = compute_imc(weight_lb, height_cm)
                    self.imc = imc
                    record.last_imc = imc
                    # The IMC's "as of" date is whichever of its two source
                    # measurements is newer -- may be this entry's own date,
                    # or an older still-current measurement on the other side.
                    record.last_imc_at = max(
                        record.last_height_at or now, record.last_weight_at or now
                    )
            record.last_visit_at = now

            self.personal_ap_snapshot = [
                {"ap_type_id": c.ap_type_id, "label": c.ap_type.name if c.ap_type_id else c.custom_label, "is_custom": c.is_custom}
                for c in record.personal_conditions.select_related("ap_type").all()
            ]
            self.family_ap_snapshot = [
                {
                    "related_patient_id": c.related_patient_id,
                    "relationship": c.relationship,
                    "relationship_other": c.relationship_other,
                    "relative_name": c.relative_name,
                    "ap_type_id": c.ap_type_id,
                    "label": c.ap_type.name if c.ap_type_id else c.custom_label,
                    "is_custom": c.is_custom,
                }
                for c in record.family_conditions.select_related("ap_type").all()
            ]
            if was_draft:
                self.status = self.Status.COMPLETED
                self.completed_at = now
                self.author = actor
            self.save()
            record.save()
        return self


class RecordPersonalCondition(TimestampedModel):
    """A living personal AP (Antecedentes Patológicos) entry on the chart --
    either a catalog APType or a free-text "Otro" (custom_label,
    is_custom=True). Removing a condition edits the living chart; it does
    not rewrite any RecordEntry's already-frozen personal_ap_snapshot."""

    record = models.ForeignKey(MedicalRecord, on_delete=models.CASCADE, related_name="personal_conditions")
    ap_type = models.ForeignKey(
        "APType", on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    custom_label = models.CharField(max_length=255, blank=True, default="")
    is_custom = models.BooleanField(default=False)

    class Meta:
        ordering = ["id"]
        constraints = [
            models.UniqueConstraint(
                fields=["record", "ap_type"],
                condition=models.Q(ap_type__isnull=False),
                name="uniq_record_personal_ap_type",
            ),
        ]

    def __str__(self) -> str:
        return self.ap_type.name if self.ap_type_id else self.custom_label


class RecordFamilyCondition(TimestampedModel):
    """A living family/heredo-familial AP entry: one row per (relative, AP)
    pair, optionally linked to an existing Patient (copied from that
    relative's own personal APs) or entered manually without a link."""

    class Relationship(models.TextChoices):
        MADRE = "MADRE", "Madre"
        PADRE = "PADRE", "Padre"
        HERMANA = "HERMANA", "Hermana"
        HERMANO = "HERMANO", "Hermano"
        HIJA = "HIJA", "Hija"
        HIJO = "HIJO", "Hijo"
        ABUELA = "ABUELA", "Abuela"
        ABUELO = "ABUELO", "Abuelo"
        TIA = "TIA", "Tía"
        TIO = "TIO", "Tío"
        OTRO = "OTRO", "Otro familiar"

    record = models.ForeignKey(MedicalRecord, on_delete=models.CASCADE, related_name="family_conditions")
    related_patient = models.ForeignKey(
        "patients.Patient", on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    relationship = models.CharField(max_length=10, choices=Relationship.choices)
    relationship_other = models.CharField(max_length=100, blank=True, default="")
    relative_name = models.CharField(max_length=200, blank=True, default="")
    ap_type = models.ForeignKey(
        "APType", on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    custom_label = models.CharField(max_length=255, blank=True, default="")
    is_custom = models.BooleanField(default=False)

    class Meta:
        ordering = ["id"]

    def __str__(self) -> str:
        label = self.ap_type.name if self.ap_type_id else self.custom_label
        return f"{self.get_relationship_display()}: {label}"


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
