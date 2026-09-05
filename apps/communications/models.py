from django.conf import settings
from django.db import models

from apps.core.fields import EncryptedCharField
from apps.core.models import TimestampedModel


class CommunicationsSettings(models.Model):
    """Singleton (pk=1) row of Comunicaciones channel configuration --
    mirrors apps.systemsettings.models.SystemSettings. Reads should mostly go
    through apps.communications.services.settings.get_communications_settings
    (a plain get_or_create, no caching layer -- this isn't a hot path)."""

    from_name = models.CharField(max_length=120, blank=True, default="")
    reply_to = models.EmailField(blank=True, default="")

    whatsapp_phone_number_id = models.CharField(max_length=64, blank=True, default="")
    whatsapp_business_account_id = models.CharField(max_length=64, blank=True, default="")
    # Write-only secrets from the caller's perspective (serializer never
    # echoes the raw value back) -- encrypted at rest like other server-side
    # secrets/PII in this codebase (apps.core.fields.EncryptedCharField).
    whatsapp_access_token = EncryptedCharField(max_length=512, blank=True, default="")
    whatsapp_app_secret = EncryptedCharField(max_length=512, blank=True, default="")
    whatsapp_verify_token = EncryptedCharField(max_length=512, blank=True, default="")
    whatsapp_default_country_code = models.CharField(max_length=5, default="+1")
    whatsapp_reminder_hours = models.PositiveIntegerField(default=24)
    whatsapp_master_enabled = models.BooleanField(default=False)

    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Communications settings"
        verbose_name_plural = "Communications settings"

    def __str__(self) -> str:
        return "Communications settings"

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)

    def whatsapp_configured(self) -> bool:
        return bool(self.whatsapp_access_token and self.whatsapp_phone_number_id)


class Template(TimestampedModel):
    class Channel(models.TextChoices):
        EMAIL = "EMAIL", "Email"
        WHATSAPP = "WHATSAPP", "WhatsApp"

    class Kind(models.TextChoices):
        AVISO = "AVISO", "Aviso"
        INFORMACION = "INFORMACION", "Informacion"
        ALERTA = "ALERTA", "Alerta"
        CITA_CREADA = "CITA_CREADA", "Cita creada"
        CITA_RECORDATORIO = "CITA_RECORDATORIO", "Cita recordatorio"
        CITA_REAGENDADA = "CITA_REAGENDADA", "Cita reagendada"
        CITA_CANCELADA = "CITA_CANCELADA", "Cita cancelada"

    channel = models.CharField(max_length=20, choices=Channel.choices)
    kind = models.CharField(max_length=30, choices=Kind.choices)
    # Meta-approved WhatsApp template name; blank for email templates.
    provider_name = models.CharField(max_length=120, blank=True, default="")
    language = models.CharField(max_length=10, default="es_DO")
    body_email = models.TextField(blank=True, default="")
    # Ordered variable names for WhatsApp templates, e.g.
    # ["nombre", "clinica", "fecha", "hora", "telefono"].
    variables_json = models.JSONField(default=list, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["channel", "kind"]
        constraints = [
            # Only one ACTIVE template per channel+kind; deactivated
            # duplicates are kept for history instead of being deleted.
            models.UniqueConstraint(
                fields=["channel", "kind"],
                condition=models.Q(is_active=True),
                name="uniq_active_template_channel_kind",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.channel}:{self.kind}"


class Message(TimestampedModel):
    class Channel(models.TextChoices):
        EMAIL = "EMAIL", "Email"
        WHATSAPP = "WHATSAPP", "WhatsApp"

    class Audience(models.TextChoices):
        STAFF = "STAFF", "Staff"
        PATIENT = "PATIENT", "Patient"

    Kind = Template.Kind

    class Priority(models.TextChoices):
        NORMAL = "NORMAL", "Normal"
        ALERTA = "ALERTA", "Alerta"

    class Status(models.TextChoices):
        DRAFT = "DRAFT", "Draft"
        QUEUED = "QUEUED", "Queued"
        SENDING = "SENDING", "Sending"
        SENT = "SENT", "Sent"
        PARTIAL = "PARTIAL", "Partial"
        FAILED = "FAILED", "Failed"
        CANCELLED = "CANCELLED", "Cancelled"

    channel = models.CharField(max_length=20, choices=Channel.choices)
    audience = models.CharField(max_length=20, choices=Audience.choices)
    kind = models.CharField(max_length=30, choices=Kind.choices)
    priority = models.CharField(max_length=10, choices=Priority.choices, default=Priority.NORMAL)
    subject = models.CharField(max_length=120, blank=True, default="")
    body = models.TextField(blank=True, default="")
    template = models.ForeignKey(
        Template, null=True, blank=True, on_delete=models.SET_NULL, related_name="messages"
    )
    # null = system-generated (appointment lifecycle hooks / reminder job).
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    scheduled_for = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.QUEUED)
    recipient_count = models.PositiveIntegerField(default=0)
    appointment = models.ForeignKey(
        "appointments.Appointment",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="communication_messages",
    )

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["-created_at"]),
            models.Index(fields=["appointment", "kind"]),
        ]

    def __str__(self) -> str:
        return f"{self.channel}:{self.audience}:{self.kind}#{self.pk}"


class Delivery(TimestampedModel):
    class Status(models.TextChoices):
        QUEUED = "QUEUED", "Queued"
        # Claimed by a send_communications run but not yet resolved SENT/
        # FAILED -- the state a delivery sits in for the duration of the
        # (usually sub-second) network call, so a concurrent run's
        # QUEUED-only claim query never picks it up too.
        SENDING = "SENDING", "Sending"
        SENT = "SENT", "Sent"
        DELIVERED = "DELIVERED", "Delivered"
        READ = "READ", "Read"
        FAILED = "FAILED", "Failed"
        UNDELIVERABLE = "UNDELIVERABLE", "Undeliverable"
        OPTED_OUT = "OPTED_OUT", "Opted out"
        CANCELLED = "CANCELLED", "Cancelled"

    message = models.ForeignKey(Message, on_delete=models.CASCADE, related_name="deliveries")
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    patient = models.ForeignKey(
        "patients.Patient", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    appointment = models.ForeignKey(
        "appointments.Appointment", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    # Resolved email or E.164 phone -- encrypted like other PII contact
    # fields (apps.patients.models.Patient.phone precedent).
    address = EncryptedCharField(max_length=255, blank=True, default="")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.QUEUED)
    attempts = models.PositiveIntegerField(default=0)
    provider_message_id = models.CharField(max_length=128, blank=True, default="")
    error = models.TextField(blank=True, default="")
    sent_at = models.DateTimeField(null=True, blank=True)
    delivered_at = models.DateTimeField(null=True, blank=True)
    read_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["message"]),
            models.Index(fields=["appointment", "status"]),
        ]

    def __str__(self) -> str:
        return f"Delivery#{self.pk} {self.status}"


class OptOut(TimestampedModel):
    patient = models.ForeignKey(
        "patients.Patient", on_delete=models.CASCADE, related_name="communications_opt_outs"
    )
    # Plain (not encrypted) -- unlike Delivery.address, this column must
    # support exact-match filtering ("is this number on the opt-out list"),
    # which Fernet's non-deterministic ciphertext cannot do without a blind
    # index (apps.core.encryption.blind_index_digits, not worth the extra
    # machinery for this small, non-clinical list).
    phone_e164 = models.CharField(max_length=32, db_index=True)
    reason = models.CharField(max_length=255, blank=True, default="")

    def __str__(self) -> str:
        return f"OptOut(patient={self.patient_id})"
