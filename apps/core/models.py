from django.db import models


class TimestampedModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class SoftDeleteManager(models.Manager):
    def get_queryset(self):
        return super().get_queryset().filter(active=True)


class SoftDeleteModel(models.Model):
    """Soft-delete flag: "deleting" a row sets active=False instead of a real
    DB delete. Kept separate from TimestampedModel (rather than merged into
    it) so AuditLog, which also inherits TimestampedModel, doesn't gain an
    active field or a filtered manager it has no use for.

    `objects` (filtered) is declared before `all_objects` (unfiltered) so it
    becomes the model's `_default_manager` -- every reverse-relation traversal
    app-wide (e.g. `ars.programs.all()`) automatically excludes inactive rows
    too, not just explicit ViewSet querysets. Forward FK/O2O access (e.g.
    `appointment.doctor`) is unaffected -- Django resolves those through the
    model's unfiltered `_base_manager`, not `_default_manager`, as long as no
    model sets `Meta.base_manager_name` (do not set it on these models).
    """

    active = models.BooleanField(default=True)
    objects = SoftDeleteManager()
    all_objects = models.Manager()

    class Meta:
        abstract = True


class AuditLog(TimestampedModel):
    """Security audit trail: who did what, when, from where."""

    class Action(models.TextChoices):
        CREATE = "CREATE", "Create"
        READ = "READ", "Read"
        UPDATE = "UPDATE", "Update"
        DELETE = "DELETE", "Delete"
        LOGIN = "LOGIN", "Login"
        LOGOUT = "LOGOUT", "Logout"
        FAILED_LOGIN = "FAILED_LOGIN", "Failed login"
        EXPORT = "EXPORT", "Export"

    user = models.ForeignKey(
        "accounts.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="audit_logs",
    )
    action = models.CharField(max_length=20, choices=Action.choices)
    target_type = models.CharField(max_length=100, blank=True)
    target_id = models.PositiveBigIntegerField(null=True, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    details = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["action", "created_at"]),
            models.Index(fields=["target_type", "target_id"]),
        ]

    def __str__(self) -> str:
        who = self.user_id or "anonymous"
        return f"{who} {self.action} {self.target_type} {self.target_id or ''}".strip()
