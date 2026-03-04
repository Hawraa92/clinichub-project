# audit/apps.py
from __future__ import annotations

from django.apps import AppConfig


class AuditConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "audit"
    verbose_name = "Audit"

    def ready(self) -> None:
        # Register signal handlers (safe import)
        try:
            from . import signals  # noqa: F401
        except Exception:
            # Don't break startup if signals are optional in some environments
            pass