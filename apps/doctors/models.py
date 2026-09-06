from django.conf import settings
from django.db import models

from apps.core.models import SoftDeleteModel, TimestampedModel


class DoctorProfile(TimestampedModel, SoftDeleteModel):
    # Nullable: a médico can exist without ever getting a login (see
    # UsuarioMedico link requirements). When linked, `user.role` must be
    # DOCTOR -- enforced in DoctorProfileSerializer.validate_user, not here.
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="doctor_profile",
        null=True,
        blank=True,
    )
    # Stored independently of `user` (not derived) so a médico has a name
    # even when unlinked. The médico is the authoritative name for a linked
    # Doctor/a user -- sync_linked_user_name() pushes these onto User
    # whenever they change (DoctorProfileSerializer.create/update,
    # apps.accounts.serializers._link_or_create_doctor_profile's link mode).
    # max_length matches User.first_name/last_name, since values sync
    # between the two.
    first_name = models.CharField(max_length=150, blank=True, default="")
    last_name = models.CharField(max_length=150, blank=True, default="")
    # Nullable (not just blank) so multiple médicos can omit it without
    # colliding on the unique index -- Postgres allows multiple NULLs under
    # a unique constraint but not multiple empty strings.
    license_number = models.CharField(max_length=50, unique=True, null=True, blank=True)
    contact_phone = models.CharField(max_length=30)
    contact_email = models.EmailField(blank=True)
    bio = models.TextField(blank=True)
    # Pre-fills the room field on the encounter admission form; still
    # user-overridable per encounter, so a stale/inactive room never blocks
    # admission (SET_NULL, not PROTECT).
    default_room = models.ForeignKey(
        "rooms.Room",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="default_for_doctors",
    )
    # Short, non-PII identifier (unlike license_number, never masked) shown
    # wherever a compact doctor reference is needed, e.g. the Encounters
    # list table. Auto-generated from pk in save() below when left blank.
    code = models.CharField(max_length=12, unique=True, null=True, blank=True)
    services = models.ManyToManyField(
        "services.Service", related_name="doctors", blank=True
    )
    # Rooms this doctor is available in -- drives the Encounters admission
    # form's room auto-fill/filtering the same way `services` drives its
    # service auto-fill/filtering. Distinct related_name from both
    # `default_room` ("default_for_doctors") and `services` ("doctors").
    rooms = models.ManyToManyField(
        "rooms.Room", related_name="assignable_doctors", blank=True
    )

    class Meta:
        ordering = ["last_name", "first_name", "code"]

    def save(self, *args, **kwargs):
        if self.code:
            self.code = self.code.upper()
        super().save(*args, **kwargs)
        if not self.code:
            # pk is only available after the first save -- assign the
            # derived code and persist it with a second, targeted write
            # (same two-phase shape as Encounter.generate_encounter_number,
            # whose value also depends on a not-yet-known pk/date).
            self.code = f"DR{self.pk:04d}"
            super().save(update_fields=["code"])

    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}".strip()

    def sync_linked_user_name(self) -> None:
        """Push this médico's name onto its linked User -- the médico is
        the authoritative name for a Doctor/a login. A targeted .update()
        (not user.save()) so it never re-runs User.save()'s staff/
        superuser role-stripping logic."""
        if self.user_id and (self.first_name or self.last_name):
            from django.contrib.auth import get_user_model

            get_user_model()._base_manager.filter(pk=self.user_id).update(
                first_name=self.first_name, last_name=self.last_name
            )

    def __str__(self) -> str:
        return self.full_name or self.code or str(self.pk)


class DoctorPhoneNumber(models.Model):
    """Additional phone numbers beyond `DoctorProfile.contact_phone` (the
    primary number, left untouched everywhere it's already read). Plain
    text, matching contact_phone's own (unencrypted) storage -- doctor
    contact info isn't treated as PII the way patient data is."""

    doctor = models.ForeignKey(
        DoctorProfile, on_delete=models.CASCADE, related_name="extra_phones"
    )
    phone = models.CharField(max_length=30)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["id"]

    def __str__(self) -> str:
        return f"{self.doctor_id}:{self.phone}"


class DoctorSchedule(TimestampedModel, SoftDeleteModel):
    """Optional presence times of a doctor at a center."""

    class Weekday(models.IntegerChoices):
        MONDAY = 0, "Monday"
        TUESDAY = 1, "Tuesday"
        WEDNESDAY = 2, "Wednesday"
        THURSDAY = 3, "Thursday"
        FRIDAY = 4, "Friday"
        SATURDAY = 5, "Saturday"
        SUNDAY = 6, "Sunday"

    doctor = models.ForeignKey(
        DoctorProfile,
        on_delete=models.CASCADE,
        related_name="schedules",
    )
    center = models.ForeignKey(
        "centers.MedicalCenter",
        on_delete=models.CASCADE,
        related_name="doctor_schedules",
    )
    weekday = models.PositiveSmallIntegerField(choices=Weekday.choices)
    start_time = models.TimeField()
    end_time = models.TimeField()

    class Meta:
        ordering = ["weekday", "start_time"]
        unique_together = ("doctor", "center", "weekday", "start_time")

    def __str__(self) -> str:
        return f"{self.doctor} {self.get_weekday_display()} {self.start_time}-{self.end_time}"
