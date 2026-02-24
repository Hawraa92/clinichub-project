# audit/models.py
from __future__ import annotations

from django.conf import settings
from django.db import models


class AuditLog(models.Model):
    ACTION_CHOICES = [
        ("create", "Create"),
        ("update", "Update"),
        ("delete", "Delete"),
        ("login", "Login"),
        ("logout", "Logout"),
        ("view", "View"),
        ("other", "Other"),
    ]

    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="audit_logs",
        verbose_name="User",
    )
    action = models.CharField(max_length=20, choices=ACTION_CHOICES, default="other")
    app_label = models.CharField(max_length=100, blank=True)
    model_name = models.CharField(max_length=100, blank=True)
    object_id = models.CharField(max_length=64, blank=True)
    object_repr = models.CharField(max_length=255, blank=True)

    path = models.CharField(max_length=500, blank=True)
    method = models.CharField(max_length=10, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)

    message = models.CharField(max_length=255, blank=True)
    extra_data = models.JSONField(default=dict, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Audit Log"
        verbose_name_plural = "Audit Logs"

    def __str__(self) -> str:
        who = getattr(self.actor, "username", None) or "Anonymous"
        target = self.object_repr or f"{self.app_label}.{self.model_name}".strip(".")
        return f"[{self.created_at:%Y-%m-%d %H:%M}] {who} {self.action} {target}"