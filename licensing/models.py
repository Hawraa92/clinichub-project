from __future__ import annotations

import uuid

from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils import timezone
from django.utils.translation import gettext_lazy as _


class Installation(models.Model):
    """
    A stable identity for this ClinicHub installation.

    The UUID is stored in the database instead of being derived only from
    hardware, so normal server upgrades do not unexpectedly invalidate a
    customer's license.
    """

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )
    display_name = models.CharField(max_length=200, blank=True)
    machine_fingerprint = models.CharField(max_length=64, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("installation")
        verbose_name_plural = _("installation")

    def __str__(self) -> str:
        return self.display_name or str(self.pk)

    @classmethod
    def get_current(cls) -> "Installation":
        installation = cls.objects.order_by("created_at").first()
        if installation is not None:
            return installation

        from .crypto import build_machine_fingerprint

        return cls.objects.create(
            display_name=getattr(settings, "LICENSE_INSTALLATION_NAME", ""),
            machine_fingerprint=build_machine_fingerprint(),
        )


class LicenseRecord(models.Model):
    class Plans(models.TextChoices):
        TRIAL = "trial", _("Trial")
        ANNUAL = "annual", _("Annual")
        PERPETUAL = "perpetual", _("Perpetual")
        CUSTOM = "custom", _("Custom")

    license_id = models.UUIDField(unique=True, db_index=True)
    installation = models.ForeignKey(
        Installation,
        on_delete=models.PROTECT,
        related_name="licenses",
    )

    product = models.CharField(max_length=80, default="clinichub")
    customer_name = models.CharField(max_length=250)
    customer_email = models.EmailField(blank=True)
    plan = models.CharField(
        max_length=20,
        choices=Plans.choices,
        default=Plans.ANNUAL,
    )

    issued_at = models.DateTimeField()
    not_before = models.DateField()
    expires_at = models.DateField(null=True, blank=True)
    grace_days = models.PositiveSmallIntegerField(default=0)
    max_offline_days = models.PositiveSmallIntegerField(default=30)

    modules = models.JSONField(default=list, blank=True)
    limits = models.JSONField(default=dict, blank=True)
    claims = models.JSONField(default=dict)
    license_token = models.TextField()

    is_active = models.BooleanField(default=True, db_index=True)
    is_revoked = models.BooleanField(default=False, db_index=True)
    activated_at = models.DateTimeField(default=timezone.now)
    activated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="activated_licenses",
    )

    last_verified_at = models.DateTimeField(null=True, blank=True)
    last_online_success_at = models.DateTimeField(null=True, blank=True)
    next_online_check_at = models.DateTimeField(null=True, blank=True)
    last_error = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-activated_at", "-created_at"]
        indexes = [
            models.Index(
                fields=["is_active", "is_revoked", "expires_at"],
                name="license_active_exp_idx",
            ),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["installation"],
                condition=Q(is_active=True, is_revoked=False),
                name="one_active_license_per_install",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.customer_name} - {self.license_id}"

    @property
    def masked_token(self) -> str:
        if len(self.license_token) < 24:
            return "********"
        return f"{self.license_token[:12]}…{self.license_token[-8:]}"


class LicenseAuditEvent(models.Model):
    class EventTypes(models.TextChoices):
        INSTALLED = "installed", _("Installed")
        VERIFIED = "verified", _("Verified")
        REJECTED = "rejected", _("Rejected")
        ONLINE_OK = "online_ok", _("Online verification succeeded")
        ONLINE_FAILED = "online_failed", _("Online verification failed")
        REVOKED = "revoked", _("Revoked")
        LIMIT_BLOCKED = "limit_blocked", _("Limit blocked")

    event_type = models.CharField(max_length=30, choices=EventTypes.choices)
    license = models.ForeignKey(
        LicenseRecord,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="audit_events",
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="license_audit_events",
    )
    success = models.BooleanField(default=True)
    message = models.TextField(blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(
                fields=["event_type", "created_at"],
                name="license_event_date_idx",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.get_event_type_display()} - {self.created_at:%Y-%m-%d %H:%M}"
