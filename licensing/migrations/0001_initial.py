# Generated for ClinicHub Licensing.

import uuid

import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="Installation",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                ("display_name", models.CharField(blank=True, max_length=200)),
                (
                    "machine_fingerprint",
                    models.CharField(blank=True, max_length=64),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "verbose_name": "installation",
                "verbose_name_plural": "installation",
            },
        ),
        migrations.CreateModel(
            name="LicenseRecord",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "license_id",
                    models.UUIDField(db_index=True, unique=True),
                ),
                (
                    "product",
                    models.CharField(default="clinichub", max_length=80),
                ),
                ("customer_name", models.CharField(max_length=250)),
                ("customer_email", models.EmailField(blank=True, max_length=254)),
                (
                    "plan",
                    models.CharField(
                        choices=[
                            ("trial", "Trial"),
                            ("annual", "Annual"),
                            ("perpetual", "Perpetual"),
                            ("custom", "Custom"),
                        ],
                        default="annual",
                        max_length=20,
                    ),
                ),
                ("issued_at", models.DateTimeField()),
                ("not_before", models.DateField()),
                ("expires_at", models.DateField(blank=True, null=True)),
                ("grace_days", models.PositiveSmallIntegerField(default=0)),
                ("max_offline_days", models.PositiveSmallIntegerField(default=30)),
                ("modules", models.JSONField(blank=True, default=list)),
                ("limits", models.JSONField(blank=True, default=dict)),
                ("claims", models.JSONField(default=dict)),
                ("license_token", models.TextField()),
                ("is_active", models.BooleanField(db_index=True, default=True)),
                ("is_revoked", models.BooleanField(db_index=True, default=False)),
                (
                    "activated_at",
                    models.DateTimeField(default=django.utils.timezone.now),
                ),
                ("last_verified_at", models.DateTimeField(blank=True, null=True)),
                (
                    "last_online_success_at",
                    models.DateTimeField(blank=True, null=True),
                ),
                (
                    "next_online_check_at",
                    models.DateTimeField(blank=True, null=True),
                ),
                ("last_error", models.TextField(blank=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "activated_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="activated_licenses",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "installation",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="licenses",
                        to="licensing.installation",
                    ),
                ),
            ],
            options={
                "ordering": ["-activated_at", "-created_at"],
            },
        ),
        migrations.CreateModel(
            name="LicenseAuditEvent",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "event_type",
                    models.CharField(
                        choices=[
                            ("installed", "Installed"),
                            ("verified", "Verified"),
                            ("rejected", "Rejected"),
                            ("online_ok", "Online verification succeeded"),
                            ("online_failed", "Online verification failed"),
                            ("revoked", "Revoked"),
                            ("limit_blocked", "Limit blocked"),
                        ],
                        max_length=30,
                    ),
                ),
                ("success", models.BooleanField(default=True)),
                ("message", models.TextField(blank=True)),
                ("metadata", models.JSONField(blank=True, default=dict)),
                (
                    "ip_address",
                    models.GenericIPAddressField(blank=True, null=True),
                ),
                (
                    "created_at",
                    models.DateTimeField(auto_now_add=True, db_index=True),
                ),
                (
                    "actor",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="license_audit_events",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "license",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="audit_events",
                        to="licensing.licenserecord",
                    ),
                ),
            ],
            options={
                "ordering": ["-created_at"],
            },
        ),
        migrations.AddIndex(
            model_name="licenserecord",
            index=models.Index(
                fields=["is_active", "is_revoked", "expires_at"],
                name="license_active_exp_idx",
            ),
        ),
        migrations.AddConstraint(
            model_name="licenserecord",
            constraint=models.UniqueConstraint(
                condition=models.Q(is_active=True, is_revoked=False),
                fields=("installation",),
                name="one_active_license_per_install",
            ),
        ),
        migrations.AddIndex(
            model_name="licenseauditevent",
            index=models.Index(
                fields=["event_type", "created_at"],
                name="license_event_date_idx",
            ),
        ),
    ]
