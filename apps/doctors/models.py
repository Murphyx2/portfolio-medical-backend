from django.conf import settings
from django.db import models

from apps.core.models import SoftDeleteModel, TimestampedModel


class DoctorProfile(TimestampedModel, SoftDeleteModel):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="doctor_profile",
    )
    specialty = models.CharField(max_length=150)
    license_number = models.CharField(max_length=50, unique=True)
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

    class Meta:
        ordering = ["user__last_name", "user__first_name"]

    @property
    def full_name(self) -> str:
        return self.user.get_full_name() or self.user.username

    def __str__(self) -> str:
        return f"{self.full_name} ({self.specialty})"


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
