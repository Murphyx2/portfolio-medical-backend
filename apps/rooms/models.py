from django.db import models

from apps.core.models import SoftDeleteModel, TimestampedModel


class RoomType(TimestampedModel, SoftDeleteModel):
    name = models.CharField(max_length=255, unique=True)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class Room(TimestampedModel, SoftDeleteModel):
    code = models.CharField(max_length=20, unique=True)
    name = models.CharField(max_length=200)
    room_type = models.ForeignKey(RoomType, on_delete=models.PROTECT, related_name="rooms")
    center = models.ForeignKey("centers.MedicalCenter", on_delete=models.PROTECT, related_name="rooms")
    floor_area = models.CharField(max_length=100, blank=True)
    capacity = models.PositiveIntegerField(null=True, blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["name"]

    def save(self, *args, **kwargs):
        self.code = self.code.upper()
        self.floor_area = self.floor_area.upper()
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"{self.code} — {self.name}"
