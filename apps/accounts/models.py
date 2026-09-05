from django.contrib.auth.models import AbstractUser
from django.db import models
from django.utils import timezone


class User(AbstractUser):
    """Custom user with role-based access for the medical system."""

    class Role(models.TextChoices):
        ADMIN = "ADMIN", "Admin"
        DOCTOR = "DOCTOR", "Doctor"
        RECEPTIONIST = "RECEPTIONIST", "Receptionist"
        IT = "IT", "IT"
        NURSE = "NURSE", "Nurse"
        CENTER_MANAGER = "CENTER_MANAGER", "Center Manager"

    role = models.CharField(
        max_length=20,
        choices=Role.choices,
        default=Role.RECEPTIONIST,
        verbose_name="Role",
    )

    # Brute-force lockout (see accounts/views.py::LoginView): incremented on
    # each failed login, reset on success. Reaching LOCKOUT_THRESHOLD sets
    # locked_until LOCKOUT_MINUTES into the future; is_locked simply checks
    # whether that timestamp is still ahead of now, so an expired lock needs
    # no separate cleanup job.
    LOCKOUT_THRESHOLD = 5
    LOCKOUT_MINUTES = 30

    failed_login_count = models.PositiveIntegerField(default=0)
    locked_until = models.DateTimeField(null=True, blank=True)

    # Which center this staff member belongs to, for RECEPTIONIST, IT,
    # NURSE and CENTER_MANAGER (see apps/core/services/scoping.py --
    # resolve_accessible_center_ids). ADMIN ignores this and always sees
    # every center. DOCTOR ignores this too -- doctors use the many-to-many
    # DoctorCenterBinding instead, since a doctor can work at more than one
    # center. Left null: the staff member is center-agnostic (sees
    # everything) until an admin assigns them a center -- the safe default
    # so existing accounts aren't locked out the moment scoping is enabled.
    center = models.ForeignKey(
        "centers.MedicalCenter",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="managed_by",
    )

    @property
    def is_locked(self) -> bool:
        return bool(self.locked_until and self.locked_until > timezone.now())

    def save(self, *args, **kwargs):
        if self.role == self.Role.ADMIN:
            self.is_staff = True
            self.is_superuser = True
        else:
            # Every non-ADMIN role is explicitly stripped of Django admin
            # access. This also clears is_staff/is_superuser when an ADMIN is
            # demoted to another role (otherwise the demoted account would keep
            # Django admin, exposing decrypted PII to a non-admin role).
            self.is_staff = False
            self.is_superuser = False
        super().save(*args, **kwargs)

    @property
    def is_admin(self) -> bool:
        return self.role == self.Role.ADMIN

    @property
    def is_doctor(self) -> bool:
        return self.role == self.Role.DOCTOR

    @property
    def is_receptionist(self) -> bool:
        return self.role == self.Role.RECEPTIONIST

    @property
    def is_it(self) -> bool:
        return self.role == self.Role.IT

    @property
    def is_nurse(self) -> bool:
        return self.role == self.Role.NURSE

    @property
    def is_center_manager(self) -> bool:
        return self.role == self.Role.CENTER_MANAGER

    def __str__(self) -> str:
        return f"{self.get_full_name() or self.username} ({self.get_role_display()})"
