from django.db import models

from apps.core.models import SoftDeleteModel, TimestampedModel


class Room(TimestampedModel, SoftDeleteModel):
    class RoomType(models.TextChoices):
        CONSULTATION = "CONSULTATION", "Consultation"
        PROCEDURE = "PROCEDURE", "Procedure"
        LABORATORY = "LABORATORY", "Laboratory"
        IMAGING = "IMAGING", "Imaging"
        WAITING = "WAITING", "Waiting area"
        OTHER = "OTHER", "Other"

    code = models.CharField(max_length=20, unique=True)
    name = models.CharField(max_length=200)
    room_type = models.CharField(max_length=20, choices=RoomType.choices, default=RoomType.CONSULTATION)
    center = models.ForeignKey("centers.MedicalCenter", on_delete=models.PROTECT, related_name="rooms")
    floor_area = models.CharField(max_length=100, blank=True)
    capacity = models.PositiveIntegerField(null=True, blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return f"{self.code} — {self.name}"
