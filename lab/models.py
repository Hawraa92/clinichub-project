# lab/models.py
from __future__ import annotations

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import FileExtensionValidator
from django.db import models, transaction
from django.utils import timezone


class LabSettings(models.Model):
    """
    Singleton settings row for the Lab module (operational settings).
    Keep one row only (id=1). Use get_solo() to retrieve/create.
    """

    lab_name = models.CharField(max_length=120, default="ClinicHub Lab")
    lab_phone = models.CharField(max_length=40, blank=True, default="")
    lab_address = models.CharField(max_length=200, blank=True, default="")

    # Optional branding
    lab_logo = models.ImageField(upload_to="lab/settings/%Y/%m/", null=True, blank=True)

    # Upload policy
    max_upload_mb = models.PositiveIntegerField(default=10)
    allow_pdf = models.BooleanField(default=True)
    allow_images = models.BooleanField(default=True)  # jpg/png/webp...

    # Workflow
    require_verify_before_ready = models.BooleanField(default=True)

    # Report defaults
    default_result_template = models.TextField(
        blank=True,
        default="",
        help_text="Optional default text that appears in result form/report.",
    )
    footer_note = models.CharField(
        max_length=200,
        blank=True,
        default="",
        help_text="Optional footer note for lab reports.",
    )

    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Lab Settings"
        verbose_name_plural = "Lab Settings"

    def __str__(self) -> str:
        return "Lab Settings"

    @classmethod
    def get_solo(cls) -> "LabSettings":
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj


def _doctor_attachment_upload_path(instance: "LabOrder", filename: str) -> str:
    now = timezone.now()
    return f"lab/doctor_attachments/{now:%Y/%m}/{filename}"


class LabOrder(models.Model):
    class Urgency(models.TextChoices):
        NORMAL = "NORMAL", "Normal"
        URGENT = "URGENT", "Urgent"

    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending"
        IN_PROGRESS = "IN_PROGRESS", "In Progress"
        READY = "READY", "Ready"
        CANCELLED = "CANCELLED", "Cancelled"

    patient = models.ForeignKey(
        "patient.Patient",
        on_delete=models.CASCADE,
        related_name="lab_orders",
    )
    doctor = models.ForeignKey(
        "doctor.Doctor",
        on_delete=models.CASCADE,
        related_name="lab_orders",
    )

    # اختياري (إذا تحبين تربطيه بالموعد)
    appointment = models.ForeignKey(
        "appointments.Appointment",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="lab_orders",
    )

    requested_tests_text = models.TextField(
        help_text="Doctor writes requested tests in English (e.g. CBC + CRP + ESR)",
    )
    notes = models.TextField(blank=True, default="")

    # ✅ مرفق PDF من الطبيب (Referral / old report)
    doctor_attachment = models.FileField(
        upload_to=_doctor_attachment_upload_path,
        null=True,
        blank=True,
        validators=[FileExtensionValidator(["pdf"])],
        help_text="Optional: Upload a PDF (referral/old report) to help the lab.",
        verbose_name="Doctor PDF Attachment",
    )

    # ✅ Doctor read/seen tracking (for badge to disappear after opening)
    doctor_seen_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Timestamp when the doctor opened/viewed this order after it became READY.",
    )

    urgency = models.CharField(
        max_length=10,
        choices=Urgency.choices,
        default=Urgency.NORMAL,
    )
    status = models.CharField(
        max_length=15,
        choices=Status.choices,
        default=Status.PENDING,
        db_index=True,
    )

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["doctor", "status", "created_at"]),
            models.Index(fields=["patient", "created_at"]),
        ]

    def __str__(self) -> str:
        return f"LabOrder #{self.pk} - {self.patient}"

    # --------------------------
    # Workflow helpers
    # --------------------------
    def _has_verified_result(self) -> bool:
        """
        True if there is a result and it is VERIFIED.
        """
        try:
            res = self.result  # related_name="result"
        except Exception:
            return False
        return getattr(res, "status", None) == LabResult.Status.VERIFIED

    def can_mark_ready(self) -> bool:
        """
        Determine if order is allowed to become READY based on LabSettings.
        """
        settings_obj = LabSettings.get_solo()
        if settings_obj.require_verify_before_ready:
            return self._has_verified_result()
        return True

    def mark_ready(self, *, reset_doctor_seen: bool = True) -> None:
        """
        Mark order as READY (optionally reset doctor_seen_at so it appears as unread).
        Enforces LabSettings.require_verify_before_ready.
        """
        if not self.can_mark_ready():
            raise ValidationError("This order cannot be marked READY before verifying the result.")

        updates = ["status"]
        self.status = LabOrder.Status.READY

        if reset_doctor_seen:
            self.doctor_seen_at = None
            updates.append("doctor_seen_at")

        self.save(update_fields=updates)

    def mark_in_progress(self) -> None:
        if self.status != LabOrder.Status.CANCELLED:
            self.status = LabOrder.Status.IN_PROGRESS
            self.save(update_fields=["status"])

    def mark_cancelled(self) -> None:
        self.status = LabOrder.Status.CANCELLED
        self.save(update_fields=["status"])

    def reset_seen_by_doctor(self) -> None:
        """
        Useful when lab updates/overwrites a READY result and you want it to show as new again.
        """
        if self.doctor_seen_at is not None:
            self.doctor_seen_at = None
            self.save(update_fields=["doctor_seen_at"])

    def mark_seen_by_doctor(self) -> None:
        """
        Mark the order as seen by the doctor (only once).
        Typically called when doctor opens the order detail while status is READY.
        """
        if self.status == LabOrder.Status.READY and self.doctor_seen_at is None:
            self.doctor_seen_at = timezone.now()
            self.save(update_fields=["doctor_seen_at"])


def _lab_result_upload_path(instance: "LabResult", filename: str) -> str:
    now = timezone.now()
    return f"lab/results/{now:%Y/%m}/{filename}"


class LabResult(models.Model):
    class Status(models.TextChoices):
        DRAFT = "DRAFT", "Draft"
        VERIFIED = "VERIFIED", "Verified"

    order = models.OneToOneField(
        LabOrder,
        on_delete=models.CASCADE,
        related_name="result",
    )

    result_text = models.TextField(blank=True, default="")

    # ملف نتيجة PDF/صورة (اختياري)
    attachment = models.FileField(
        upload_to=_lab_result_upload_path,
        null=True,
        blank=True,
        validators=[FileExtensionValidator(["pdf", "jpg", "jpeg", "png", "webp"])],
        help_text="Optional: upload PDF or image (jpg/png/webp).",
    )

    status = models.CharField(
        max_length=10,
        choices=Status.choices,
        default=Status.DRAFT,
        db_index=True,
    )

    verified_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="verified_lab_results",
    )
    verified_at = models.DateTimeField(null=True, blank=True)

    updated_at = models.DateTimeField(auto_now=True)

    def clean(self) -> None:
        """
        Basic consistency checks.
        """
        if self.status == LabResult.Status.VERIFIED:
            if not self.verified_at:
                raise ValidationError({"verified_at": "verified_at is required when status is VERIFIED."})
            if not self.verified_by_id:
                raise ValidationError({"verified_by": "verified_by is required when status is VERIFIED."})

    @transaction.atomic
    def verify(self, user) -> None:
        """
        Verify the result and (importantly) mark the linked order as READY + reset doctor_seen_at
        so the doctor can see it as new/unread.
        """
        # Lock the order row to avoid race conditions
        LabOrder.objects.select_for_update().filter(pk=self.order_id).exists()

        self.status = LabResult.Status.VERIFIED
        self.verified_by = user
        self.verified_at = timezone.now()
        self.save(update_fields=["status", "verified_by", "verified_at", "updated_at"])

        # ✅ Key fix: push order to READY & make it appear unread to doctor
        order = self.order
        order.status = LabOrder.Status.READY
        order.doctor_seen_at = None
        order.save(update_fields=["status", "doctor_seen_at"])

    @transaction.atomic
    def mark_draft(self) -> None:
        """
        Return result to DRAFT. Does NOT change the order status automatically
        (you can decide that in views).
        """
        self.status = LabResult.Status.DRAFT
        self.verified_by = None
        self.verified_at = None
        self.save(update_fields=["status", "verified_by", "verified_at", "updated_at"])

    def __str__(self) -> str:
        return f"Result for Order #{self.order_id}"
