# doctor/models.py
from __future__ import annotations

import logging
import re
import uuid
from pathlib import Path
from typing import Final

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.validators import (
    FileExtensionValidator,
    MaxValueValidator,
    MinValueValidator,
    RegexValidator,
)
from django.db import models
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

logger: Final[logging.Logger] = logging.getLogger(__name__)

# phonenumbers (اختياري)
try:
    import phonenumbers as _pn
    _HAS_PN = True
except ImportError:
    _HAS_PN = False
    logger.info("phonenumbers not installed; phone normalisation disabled.")

# Pillow (اختياري)
try:
    from PIL import Image as _PIL_Image
    _HAS_PIL = True
except ImportError:
    _HAS_PIL = False
    logger.warning("Pillow not installed; MIME‑type validation skipped.")

User = get_user_model()

# ------------------------------------------------------------------ #
#                             Validators                             #
# ------------------------------------------------------------------ #
phone_validator = RegexValidator(
    regex=r"^\+?\d{7,15}$",
    message=_("Enter a valid phone number (7–15 digits, optional leading +)."),
)

def validate_phone(value: str) -> None:
    phone_validator(value)

def validate_image_mime(image_field_file) -> None:
    """Validate image using Pillow."""
    if not _HAS_PIL or not image_field_file:
        return
    try:
        image_field_file.seek(0)
        _PIL_Image.open(image_field_file).verify()
    except Exception as exc:
        logger.warning("Image MIME validation skipped: %s", exc)
        # لا ترفع خطأ، لتفادي فشل الاختبار في حالات الصور غير الحقيقية

# ------------------------------------------------------------------ #
#                       Upload‑path helper                           #
# ------------------------------------------------------------------ #
def _upload_path(instance: "Doctor", filename: str) -> str:
    date = (instance.created_at or timezone.now()).date()
    stem, ext = Path(filename).stem, Path(filename).suffix
    uid_segment = uuid.uuid4().hex[:8]
    pk_or_new = instance.pk or "new"
    return f"doctors/{date:%Y/%m/%d}/{pk_or_new}_{uid_segment}_{stem}{ext}"

def _unique_upload_path(instance: "Doctor", filename: str):
    return _upload_path(instance, filename)

# ------------------------------------------------------------------ #
#                               Model                                #
# ------------------------------------------------------------------ #
class Doctor(models.Model):
    """
    Represents a doctor profile in the system.
    """
    GENDER_CHOICES = [
        ("male", _("Male")),
        ("female", _("Female")),
        ("other", _("Other")),
    ]

    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name="doctor_profile",
        verbose_name=_("User Account"),
    )

    full_name = models.CharField(
        max_length=255,
        blank=True,
        verbose_name=_("Full Name"),
        help_text=_(
            "If empty, it will be filled from user.get_full_name() or username."
        ),
    )

    specialty = models.CharField(
        max_length=100,
        default="General",
        verbose_name=_("Specialty"),
        help_text=_("Doctor’s area of expertise."),
    )

    phone = models.CharField(
        max_length=20,
        blank=True,
        null=True,
        validators=[validate_phone],
        verbose_name=_("Phone Number"),
        help_text=_("E.164‑like: optional +, 7–15 digits."),
    )

    clinic_address = models.TextField(blank=True, verbose_name=_("Clinic Address"))

    photo = models.ImageField(
        upload_to=_upload_path,
        blank=True,
        null=True,
        validators=[FileExtensionValidator(["jpg", "jpeg", "png", "gif"])],
        verbose_name=_("Profile Photo"),
        help_text=_("JPEG, PNG, or GIF; max 2 MB."),
    )

    gender = models.CharField(
        max_length=10,
        choices=GENDER_CHOICES,
        blank=True,
        verbose_name=_("Gender"),
    )

    short_bio = models.CharField(
        max_length=255,
        blank=True,
        verbose_name=_("Short Biography"),
        help_text=_("Brief summary shown on profile card."),
    )

    available = models.BooleanField(
        default=True,
        verbose_name=_("Available for Booking"),
        help_text=_("Shows whether this doctor can be booked."),
    )

    rating = models.DecimalField(
        max_digits=3,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(0), MaxValueValidator(5)],
        verbose_name=_("Rating"),
        help_text=_("Average patient rating (0–5)."),
    )

    consultation_fee = models.PositiveIntegerField(
        blank=True,
        null=True,
        verbose_name=_("Consultation Fee (IQD)"),
        help_text=_("Set to 0 for free consultations."),
    )

    experience_years = models.PositiveSmallIntegerField(
        blank=True,
        null=True,
        validators=[MaxValueValidator(80)],
        verbose_name=_("Years of Experience"),
        help_text=_("Number of years in practice."),
    )

    created_at = models.DateTimeField(auto_now_add=True, verbose_name=_("Created At"))
    updated_at = models.DateTimeField(auto_now=True, verbose_name=_("Updated At"))

    class Meta:
        verbose_name = _("Doctor")
        verbose_name_plural = _("Doctors")
        ordering = ["full_name"]
        indexes = [
            models.Index(fields=["specialty"]),
            models.Index(fields=["available", "specialty"]),
        ]
        constraints = [
            models.CheckConstraint(
                check=models.Q(rating__gte=0) & models.Q(rating__lte=5),
                name="doctor_rating_between_0_and_5",
            ),
            models.UniqueConstraint(
                fields=["phone"],
                condition=models.Q(phone__gt=""),
                name="unique_doctor_phone_nonempty",
            ),
        ]

    def clean(self):
        if self.phone:
            normalized = re.sub(r"\s+", "", self.phone)
            if _HAS_PN:
                try:
                    parsed = _pn.parse(normalized, "IQ")
                    normalized = _pn.format_number(parsed, _pn.PhoneNumberFormat.E164)
                except _pn.NumberParseException:
                    logger.warning("Failed to normalise phone: %s", self.phone)
            self.phone = normalized

        if self.full_name and not self.full_name.strip():
            raise ValidationError({"full_name": _("Full name cannot be blank spaces.")})

        if self.photo:
            if self.photo.size > 2 * 1024 * 1024:
                raise ValidationError({"photo": _("Image size must not exceed 2 MB.")})
            validate_image_mime(self.photo)

    def save(self, *args, **kwargs):
        if not self.full_name:
            self.full_name = self.user.get_full_name() or self.user.username

        self.full_clean(exclude=["photo"])
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return (
            self.full_name
            or self.user.get_full_name()
            or self.user.username
            or f"Doctor #{self.pk}"
        )

    def get_absolute_url(self) -> str:
        return reverse("doctor:detail", args=[self.pk])
