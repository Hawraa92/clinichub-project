# audit/models.py
from __future__ import annotations

import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models


class AuditLog(models.Model):
    class Actions(models.TextChoices):
        CREATE = "create", "Create"
        UPDATE = "update", "Update"
        DELETE = "delete", "Delete"
        LOGIN = "login", "Login"
        LOGOUT = "logout", "Logout"
        VIEW = "view", "View"
        OTHER = "other", "Other"

    # ✅ Stable event identifier (helps correlation across logs/exports)
    event_id = models.UUIDField(default=uuid.uuid4, editable=False, unique=True, db_index=True)

    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,  # keeps log even if user is removed
        null=True,
        blank=True,
        related_name="audit_logs",
        verbose_name="User",
        db_index=True,
    )

    # Optional: keep role snapshot (helps if role changes later)
    actor_role = models.CharField(max_length=32, blank=True, db_index=True)

    action = models.CharField(
        max_length=20,
        choices=Actions.choices,
        default=Actions.OTHER,
        db_index=True,
    )

    app_label = models.CharField(max_length=100, blank=True, db_index=True)
    model_name = models.CharField(max_length=100, blank=True, db_index=True)
    object_id = models.CharField(max_length=64, blank=True, db_index=True)
    object_repr = models.CharField(max_length=255, blank=True)

    path = models.CharField(max_length=500, blank=True, db_index=True)
    method = models.CharField(max_length=10, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)

    # Helps troubleshooting without storing PHI
    request_id = models.CharField(max_length=64, blank=True, db_index=True)
    user_agent = models.CharField(max_length=512, blank=True)

    message = models.CharField(max_length=255, blank=True)
    extra_data = models.JSONField(default=dict, blank=True)

    created_at = models.DateTimeField(auto_now_add=True, editable=False, db_index=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Audit Log"
        verbose_name_plural = "Audit Logs"
        indexes = [
            models.Index(fields=["created_at", "action"], name="idx_audit_time_action"),
            models.Index(fields=["app_label", "model_name", "object_id"], name="idx_audit_target"),
        ]

    def __str__(self) -> str:
        actor = self.actor
        who = ""
        try:
            who = (actor.get_full_name() or "").strip() if actor else ""
        except Exception:
            who = ""
        if not who and actor:
            who = (getattr(actor, "email", "") or getattr(actor, "username", "") or "").strip()
        who = who or "Anonymous"

        target = self.object_repr or f"{self.app_label}.{self.model_name}".strip(".")
        return f"[{self.created_at:%Y-%m-%d %H:%M}] {who} {self.action} {target}"

    # ✅ Append-only enforcement (application-level)
    def save(self, *args, **kwargs):
        if self.pk is not None:
            raise ValidationError("AuditLog is append-only: updates are not allowed.")
        # best-effort snapshot of role at time of event
        if not self.actor_role and self.actor:
            self.actor_role = str(getattr(self.actor, "role", "") or "").strip().lower()
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("AuditLog is append-only: deletes are not allowed.")