from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models


class SystemSettings(models.Model):
    """Singleton (pk=1) row of runtime-editable operational parameters.

    ADMIN can read/write every field; IT is read-only (see
    ``apps.core.permissions.IsAdminOrITReadOnly``); every other role is
    denied. Explicit typed columns (rather than a generic key/value table)
    buy per-field range validation and simple form binding -- see
    SETTINGS_PAGE_PLAN.md section 2 for the canonical parameter table
    (default + allowed range) each field below mirrors.

    Reads should almost always go through ``apps.systemsettings.services.
    get_settings()`` (cached, TTL-backstopped, degrades to hardcoded
    defaults on failure) rather than querying this model directly.
    """

    # --- Login & Security ---
    login_lockout_threshold = models.PositiveIntegerField(
        default=5,
        validators=[MinValueValidator(1), MaxValueValidator(50)],
        help_text="Failed logins before an account is locked.",
    )
    login_lockout_minutes = models.PositiveIntegerField(
        default=30,
        validators=[MinValueValidator(5), MaxValueValidator(1440)],
        help_text="Lockout duration, in minutes.",
    )
    password_min_length = models.PositiveIntegerField(
        default=8,
        validators=[MinValueValidator(8), MaxValueValidator(64)],
        help_text="Minimum password length enforced at creation/reset.",
    )

    # --- Sessions ---
    access_token_lifetime_minutes = models.PositiveIntegerField(
        default=15,
        validators=[MinValueValidator(5), MaxValueValidator(60)],
        help_text=(
            "JWT access token lifetime, in minutes. Capped at 60: access "
            "tokens have no revocation on logout (only the refresh token is "
            "blacklisted), so this range bounds that exposure window."
        ),
    )
    refresh_token_lifetime_days = models.PositiveIntegerField(
        default=3,
        validators=[MinValueValidator(1), MaxValueValidator(30)],
        help_text="JWT refresh token lifetime, in days.",
    )

    # --- Rate limits ---
    login_rate_limit_per_min = models.PositiveIntegerField(
        default=10,
        validators=[MinValueValidator(3), MaxValueValidator(120)],
        help_text="Login attempts allowed per IP per minute.",
    )
    anon_rate_limit_per_min = models.PositiveIntegerField(
        default=60,
        validators=[MinValueValidator(10), MaxValueValidator(1000)],
        help_text="Anonymous API requests allowed per minute.",
    )
    user_rate_limit_per_min = models.PositiveIntegerField(
        default=300,
        validators=[MinValueValidator(30), MaxValueValidator(5000)],
        help_text="Authenticated API requests allowed per minute.",
    )

    # --- Data & Media ---
    max_image_upload_mb = models.PositiveIntegerField(
        default=10,
        validators=[MinValueValidator(1), MaxValueValidator(100)],
        help_text=(
            "Maximum record-image upload size, in MB. Keep at or below the "
            "nginx client_max_body_size ceiling (100 MB in prod) or larger "
            "uploads 413 before Django's validation ever runs."
        ),
    )
    media_token_ttl_minutes = models.PositiveIntegerField(
        default=60,
        validators=[MinValueValidator(5), MaxValueValidator(1440)],
        help_text=(
            "Signed media-URL token lifetime, in minutes. A longer TTL "
            "widens the replay window for a leaked signed media URL."
        ),
    )
    default_page_size = models.PositiveIntegerField(
        default=20,
        validators=[MinValueValidator(5), MaxValueValidator(100)],
        help_text="Default page size for list endpoints (still capped at 200).",
    )

    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "System settings"
        verbose_name_plural = "System settings"

    def __str__(self) -> str:
        return "System settings"

    def save(self, *args, **kwargs):
        # Enforce the singleton invariant at the model layer, not just by
        # convention -- every save lands on pk=1 regardless of what the
        # caller set.
        self.pk = 1
        super().save(*args, **kwargs)
