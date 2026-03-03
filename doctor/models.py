# doctor/models.py
from __future__ import annotations

import logging
import re
import uuid
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Final, Optional

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import (
    FileExtensionValidator,
    MaxValueValidator,
    MinValueValidator,
    RegexValidator,
)
from django.db import models, transaction
from django.db.models import Avg, Count
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

logger: Final[logging.Logger] = logging.getLogger(__name__)

# ------------------------------------------------------------------ #
# Optional deps
# ------------------------------------------------------------------ #

# phonenumbers (optional)
try:
    import phonenumbers as _pn

    _HAS_PN: Final[bool] = True
except ImportError:  # pragma: no cover
    _HAS_PN = False
    logger.info("phonenumbers not installed; phone normalisation disabled.")

# Pillow (optional)
try:
    from PIL import Image as _PIL_Image

    _HAS_PIL: Final[bool] = True
except ImportError:  # pragma: no cover
    _HAS_PIL = False
    logger.warning("Pillow not installed; MIME-type validation skipped.")


# ------------------------------------------------------------------ #
# Validators / Normalizers
# ------------------------------------------------------------------ #

phone_validator = RegexValidator(
    regex=r"^\+?\d{7,15}$",
    message=_("Enter a valid phone number (7–15 digits, optional leading +)."),
)

# HEX color: allow blank OR #A1B2C3
hex_or_blank_validator = RegexValidator(
    regex=r"^$|^#([0-9a-fA-F]{6})$",
    message=_("Enter HEX color like #A1B2C3 (or leave blank)."),
)


def _normalize_spaces(value: str) -> str:
    return " ".join((value or "").split()).strip()


def _normalize_blankable_str(value: str | None) -> str:
    """
    For blank='' CharField/TextField:
    - trims/collapses spaces
    - returns '' instead of None
    """
    if value is None:
        return ""
    return _normalize_spaces(value)


def _normalize_phone(value: str | None) -> str | None:
    """
    Normalize phone to digits + optional leading +.
    Accepts spaces/dashes/parentheses/dots.
    Returns None for empty/blank.
    """
    if value is None:
        return None

    v = str(value).strip()
    if not v:
        return None

    v = v.replace(" ", "").replace("-", "").replace("(", "").replace(")", "").replace(".", "")
    v = re.sub(r"[^\d+]", "", v)

    # allow only one leading '+'
    if "+" in v and not v.startswith("+"):
        v = v.replace("+", "")
    if v.startswith("+"):
        v = "+" + re.sub(r"[^\d]", "", v[1:])
    else:
        v = re.sub(r"[^\d]", "", v)

    return v or None


def validate_phone(value: str) -> None:
    """
    Accepts common local input formats, validates after normalization.
    Uses phonenumbers(IQ) if available; falls back to regex.
    """
    if value in (None, ""):
        return

    normalized = _normalize_phone(value)
    if not normalized:
        raise ValidationError(
            _("%(value)s is not a valid phone number."),
            params={"value": value},
        )

    if _HAS_PN:
        try:
            parsed = _pn.parse(normalized, "IQ")
            if not _pn.is_possible_number(parsed) or not _pn.is_valid_number(parsed):
                raise ValidationError(
                    _("%(value)s is not a valid phone number."),
                    params={"value": value},
                )
            return
        except ValidationError:
            raise
        except Exception:
            # fallback to regex
            pass

    phone_validator(normalized)


def validate_hex_or_blank(value: str) -> None:
    hex_or_blank_validator(value or "")


def _is_svg(name: str) -> bool:
    try:
        return Path(name).suffix.lower() == ".svg"
    except Exception:
        return False


def validate_image_mime(image_field_file) -> None:
    """
    Validate image using Pillow.
    - If SVG: skip (Pillow doesn't support SVG verify).
    - If Pillow not installed or empty: skip silently.
    - If content is invalid and Pillow can inspect it: raise ValidationError.
    """
    if not image_field_file:
        return

    try:
        name = str(getattr(image_field_file, "name", "") or "")
        if name and _is_svg(name):
            return
    except Exception:
        pass

    if not _HAS_PIL:
        return

    try:
        if hasattr(image_field_file, "open"):
            try:
                image_field_file.open("rb")
            except Exception:
                pass

        if hasattr(image_field_file, "seek"):
            image_field_file.seek(0)

        img = _PIL_Image.open(image_field_file)
        img.verify()

        if hasattr(image_field_file, "seek"):
            image_field_file.seek(0)

    except ValidationError:
        raise
    except Exception as exc:  # pragma: no cover
        logger.warning("Image validation failed: %s", exc)
        raise ValidationError(_("Uploaded file is not a valid image.")) from exc


def _validate_file_size(field_file, *, field_name: str, max_mb: int = 2, kind_label: str = "File") -> None:
    """
    Strict file size validation without swallowing ValidationError.
    """
    if not field_file:
        return

    max_bytes = max_mb * 1024 * 1024

    try:
        size = getattr(field_file, "size", None)
    except Exception as exc:  # pragma: no cover
        logger.debug("Could not read %s size for %s: %s", kind_label, field_name, exc)
        size = None

    if size is not None and size > max_bytes:
        raise ValidationError({field_name: _(f"{kind_label} size must not exceed {max_mb} MB.")})


def _validate_upload_image(field_file, *, field_name: str, max_mb: int = 2, kind_label: str = "Image") -> None:
    _validate_file_size(field_file, field_name=field_name, max_mb=max_mb, kind_label=kind_label)
    validate_image_mime(field_file)


# ------------------------------------------------------------------ #
# Upload-path helpers
# ------------------------------------------------------------------ #


def _dated_path(prefix: str, created_at, pk_or_new: str, filename: str) -> str:
    dt = (created_at or timezone.now()).date()
    stem, ext = Path(filename).stem, Path(filename).suffix
    uid_segment = uuid.uuid4().hex[:8]
    return f"{prefix}/{dt:%Y/%m/%d}/{pk_or_new}_{uid_segment}_{stem}{ext}"


def doctor_photo_upload_to(instance: "Doctor", filename: str) -> str:
    return _dated_path("doctors/photos", instance.created_at, str(instance.pk or "new"), filename)


def doctor_cover_upload_to(instance: "Doctor", filename: str) -> str:
    return _dated_path("doctors/covers", instance.created_at, str(instance.pk or "new"), filename)


def doctor_brand_upload_to(instance: "Doctor", filename: str) -> str:
    return _dated_path("doctors/branding", instance.created_at, str(instance.pk or "new"), filename)


def specialty_asset_upload_to(instance: "Specialty", filename: str) -> str:
    dt = (instance.created_at or timezone.now()).date()
    stem, ext = Path(filename).stem, Path(filename).suffix
    uid_segment = uuid.uuid4().hex[:8]
    code = (instance.code or "specialty").lower()
    return f"specialties/{dt:%Y/%m}/{code}_{uid_segment}_{stem}{ext}"


# ------------------------------------------------------------------ #
# Backward-compatible aliases (IMPORTANT for old migrations)
# ------------------------------------------------------------------ #


def _upload_path(instance: "Doctor", filename: str) -> str:
    return doctor_photo_upload_to(instance, filename)


def _unique_upload_path(instance: "Doctor", filename: str) -> str:
    return _upload_path(instance, filename)


# ------------------------------------------------------------------ #
# Specialty
# ------------------------------------------------------------------ #


class Specialty(models.Model):
    name = models.CharField(
        max_length=120,
        unique=True,
        verbose_name=_("Specialty Name"),
        help_text=_("Example: Dermatology, Cardiology, General Surgery."),
    )

    code = models.SlugField(
        max_length=80,
        unique=True,
        verbose_name=_("Code"),
        help_text=_("URL/identifier-friendly code. Example: dermatology, cardiology."),
    )

    is_public = models.BooleanField(
        default=True,
        db_index=True,
        verbose_name=_("Show Publicly"),
        help_text=_("If disabled, this specialty will not appear in public filters/pages."),
    )

    icon = models.FileField(
        upload_to=specialty_asset_upload_to,
        blank=True,
        null=True,
        verbose_name=_("Specialty Icon / Illustration"),
        help_text=_("SVG recommended. PNG/JPG also supported."),
        validators=[FileExtensionValidator(["svg", "png", "jpg", "jpeg", "webp"])],
    )

    primary_color = models.CharField(
        max_length=20,
        blank=True,
        default="",
        validators=[validate_hex_or_blank],
        verbose_name=_("Primary Color"),
        help_text=_("Example: #2563eb (leave blank for default)."),
    )

    accent_color = models.CharField(
        max_length=20,
        blank=True,
        default="",
        validators=[validate_hex_or_blank],
        verbose_name=_("Accent Color"),
        help_text=_("Example: #0d9488 (leave blank for default)."),
    )

    created_at = models.DateTimeField(auto_now_add=True, verbose_name=_("Created At"))
    updated_at = models.DateTimeField(auto_now=True, verbose_name=_("Updated At"))

    class Meta:
        verbose_name = _("Specialty")
        verbose_name_plural = _("Specialties")
        ordering = ["name"]
        indexes = [
            models.Index(fields=["code"]),
            models.Index(fields=["name"]),
            models.Index(fields=["is_public"]),
        ]

    def clean(self):
        super().clean()

        self.name = _normalize_spaces(self.name)
        self.code = _normalize_spaces(self.code).lower()

        if not self.name:
            raise ValidationError({"name": _("Specialty name cannot be blank.")})
        if not self.code:
            raise ValidationError({"code": _("Code cannot be blank.")})

        if self.icon:
            _validate_upload_image(self.icon, field_name="icon", max_mb=2, kind_label="File")

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)

    def __str__(self) -> str:
        return self.name


# ------------------------------------------------------------------ #
# Doctor
# ------------------------------------------------------------------ #


class Doctor(models.Model):
    ENTITY_CHOICES = [
        ("doctor_m", _("Doctor (Male)")),
        ("doctor_f", _("Doctor (Female)")),
        ("clinic", _("Clinic")),
    ]

    GENDER_CHOICES = [
        ("male", _("Male")),
        ("female", _("Female")),
        ("other", _("Other")),
    ]

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="doctor_profile",
        verbose_name=_("User Account"),
    )

    entity_type = models.CharField(
        max_length=10,
        choices=ENTITY_CHOICES,
        default="doctor_m",
        verbose_name=_("Entity Type"),
        help_text=_("Male doctor, female doctor, or clinic."),
        db_index=True,
    )

    full_name = models.CharField(
        max_length=255,
        blank=True,
        default="",
        verbose_name=_("Full Name"),
        help_text=_("If empty, it will be filled from user.get_full_name() or username."),
    )

    specialty = models.CharField(
        max_length=100,
        default="General",
        verbose_name=_("Specialty (Text)"),
        help_text=_("Legacy text specialty. You can keep it or map it to Specialty Profile."),
        db_index=True,
    )

    specialty_profile = models.ForeignKey(
        Specialty,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="doctors",
        verbose_name=_("Specialty Profile"),
        help_text=_("Pick a specialty profile to enable icons/branding."),
    )

    primary_color = models.CharField(
        max_length=20,
        blank=True,
        default="",
        validators=[validate_hex_or_blank],
        verbose_name=_("Primary Color (Doctor Override)"),
        help_text=_("Optional. Overrides specialty primary color. Example: #0b4ea2"),
    )

    accent_color = models.CharField(
        max_length=20,
        blank=True,
        default="",
        validators=[validate_hex_or_blank],
        verbose_name=_("Accent Color (Doctor Override)"),
        help_text=_("Optional. Overrides specialty accent color. Example: #0d9488"),
    )

    prescription_paper_bg = models.CharField(
        max_length=7,
        blank=True,
        default="",
        validators=[validate_hex_or_blank],
        verbose_name=_("Prescription Paper Background (HEX)"),
    )

    prescription_paper_border = models.CharField(
        max_length=7,
        blank=True,
        default="",
        validators=[validate_hex_or_blank],
        verbose_name=_("Prescription Paper Border (HEX)"),
    )

    prescription_header_bg = models.CharField(
        max_length=7,
        blank=True,
        default="",
        validators=[validate_hex_or_blank],
        verbose_name=_("Prescription Header Card Background (HEX)"),
    )

    prescription_header_text_color = models.CharField(
        max_length=7,
        blank=True,
        default="",
        validators=[validate_hex_or_blank],
        verbose_name=_("Prescription Header Text Color (HEX)"),
    )

    prescription_header_line_color = models.CharField(
        max_length=7,
        blank=True,
        default="",
        validators=[validate_hex_or_blank],
        verbose_name=_("Prescription Header Line Color (HEX)"),
    )

    prescription_specialty_text_color = models.CharField(
        max_length=7,
        blank=True,
        default="",
        validators=[validate_hex_or_blank],
        verbose_name=_("Prescription Specialty Text Color (HEX)"),
    )

    prescription_patient_label_color = models.CharField(
        max_length=7,
        blank=True,
        default="",
        validators=[validate_hex_or_blank],
        verbose_name=_("Prescription Patient Labels Color (HEX)"),
    )

    prescription_patient_value_color = models.CharField(
        max_length=7,
        blank=True,
        default="",
        validators=[validate_hex_or_blank],
        verbose_name=_("Prescription Patient Values Color (HEX)"),
    )

    syndicate_registration_no = models.CharField(
        max_length=80,
        blank=True,
        default="",
        verbose_name=_("Syndicate Registration No."),
        db_index=True,
    )

    syndicate_registration_date = models.DateField(
        null=True,
        blank=True,
        verbose_name=_("Syndicate Registration Date"),
        db_index=True,
    )

    phone = models.CharField(
        max_length=20,
        blank=True,
        null=True,
        validators=[validate_phone],
        verbose_name=_("Clinic Phone Number"),
        db_index=True,
    )

    clinic_address = models.TextField(
        blank=True,
        default="",
        verbose_name=_("Clinic Address"),
    )

    photo = models.ImageField(
        upload_to=doctor_photo_upload_to,
        blank=True,
        null=True,
        validators=[FileExtensionValidator(["jpg", "jpeg", "png", "gif", "webp"])],
        verbose_name=_("Profile Photo"),
    )

    cover_photo = models.ImageField(
        upload_to=doctor_cover_upload_to,
        blank=True,
        null=True,
        validators=[FileExtensionValidator(["jpg", "jpeg", "png", "gif", "webp"])],
        verbose_name=_("Card Cover Photo"),
    )

    clinic_logo = models.ImageField(
        upload_to=doctor_brand_upload_to,
        blank=True,
        null=True,
        validators=[FileExtensionValidator(["png", "jpg", "jpeg", "webp"])],
        verbose_name=_("Clinic Logo"),
    )

    signature_image = models.ImageField(
        upload_to=doctor_brand_upload_to,
        blank=True,
        null=True,
        validators=[FileExtensionValidator(["png", "jpg", "jpeg", "webp"])],
        verbose_name=_("Doctor Signature Image"),
    )

    prescription_header_illustration = models.FileField(
        upload_to=doctor_brand_upload_to,
        blank=True,
        null=True,
        validators=[FileExtensionValidator(["svg", "png", "jpg", "jpeg", "webp"])],
        verbose_name=_("Prescription Header Illustration"),
    )

    prescription_watermark = models.FileField(
        upload_to=doctor_brand_upload_to,
        blank=True,
        null=True,
        validators=[FileExtensionValidator(["svg", "png", "jpg", "jpeg", "webp"])],
        verbose_name=_("Prescription Watermark"),
    )

    gender = models.CharField(
        max_length=10,
        choices=GENDER_CHOICES,
        blank=True,
        default="",
        verbose_name=_("Gender"),
    )

    short_bio = models.CharField(
        max_length=255,
        blank=True,
        default="",
        verbose_name=_("Short Biography"),
    )

    available = models.BooleanField(
        default=True,
        verbose_name=_("Available for Booking"),
    )

    rating = models.DecimalField(
        max_digits=3,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(0), MaxValueValidator(5)],
        verbose_name=_("Rating (Auto)"),
    )

    review_count = models.PositiveIntegerField(
        default=0,
        verbose_name=_("Review Count (Auto)"),
        db_index=True,
        editable=False,
    )

    consultation_fee = models.PositiveIntegerField(
        blank=True,
        null=True,
        verbose_name=_("Consultation Fee (IQD)"),
    )

    experience_years = models.PositiveSmallIntegerField(
        blank=True,
        null=True,
        validators=[MaxValueValidator(80)],
        verbose_name=_("Years of Experience"),
    )

    created_at = models.DateTimeField(auto_now_add=True, verbose_name=_("Created At"))
    updated_at = models.DateTimeField(auto_now=True, verbose_name=_("Updated At"))

    class Meta:
        verbose_name = _("Doctor")
        verbose_name_plural = _("Doctors")
        ordering = ["full_name"]
        indexes = [
            models.Index(fields=["entity_type"]),
            models.Index(fields=["specialty"]),
            models.Index(fields=["available", "specialty"]),
            models.Index(fields=["specialty_profile"]),
            models.Index(fields=["syndicate_registration_no"]),
            models.Index(fields=["syndicate_registration_date"]),
            models.Index(fields=["phone"]),
            models.Index(fields=["review_count"]),
        ]
        constraints = [
            models.CheckConstraint(
                check=models.Q(rating__isnull=True) | (models.Q(rating__gte=0) & models.Q(rating__lte=5)),
                name="doctor_rating_null_or_between_0_and_5",
            ),
            models.UniqueConstraint(
                fields=["phone"],
                condition=models.Q(phone__isnull=False) & ~models.Q(phone=""),
                name="unique_doctor_phone_nonempty",
            ),
        ]

    @classmethod
    def update_rating_cache_for(cls, doctor_id: int) -> None:
        agg = DoctorReview.objects.filter(doctor_id=doctor_id).aggregate(avg=Avg("rating"), cnt=Count("id"))
        cnt = int(agg.get("cnt") or 0)
        avg = agg.get("avg", None)

        if cnt <= 0 or avg is None:
            cls.objects.filter(pk=doctor_id).update(rating=None, review_count=0)
            return

        avg_dec = Decimal(str(avg)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        avg_dec = min(max(avg_dec, Decimal("0.00")), Decimal("5.00"))

        cls.objects.filter(pk=doctor_id).update(rating=avg_dec, review_count=cnt)

    def clean(self):
        super().clean()

        # ✅ فرق مهم للاختبارات:
        # إذا full_name انرسل كمسافات فقط => خطأ
        raw_full_name = self.full_name
        if isinstance(raw_full_name, str) and raw_full_name != "" and raw_full_name.strip() == "":
            raise ValidationError({"full_name": _("Full name cannot be blank spaces.")})

        # Normalize
        self.full_name = _normalize_blankable_str(self.full_name)
        self.specialty = _normalize_blankable_str(self.specialty) or "General"
        self.short_bio = _normalize_blankable_str(self.short_bio)
        self.clinic_address = _normalize_blankable_str(self.clinic_address)
        self.syndicate_registration_no = _normalize_blankable_str(self.syndicate_registration_no)

        # ✅ إذا فارغ فعلاً => نعبّيه من get_full_name وإذا فاضي هم نستخدم username
        if not self.full_name:
            derived = ""
            if getattr(self, "user_id", None):
                try:
                    derived = (self.user.get_full_name() or "").strip()
                except Exception:
                    derived = ""

                if not derived:
                    derived = (getattr(self.user, "username", "") or "").strip()

            if derived:
                self.full_name = derived
            else:
                raise ValidationError({"full_name": _("Full name is required.")})

        # Normalize phone storage
        if self.phone is not None:
            normalized = _normalize_phone(self.phone)
            if normalized:
                if _HAS_PN:
                    try:
                        parsed = _pn.parse(normalized, "IQ")
                        normalized = _pn.format_number(parsed, _pn.PhoneNumberFormat.E164)
                    except Exception:
                        logger.warning("Failed to normalise phone: %s", self.phone)
                self.phone = normalized
            else:
                self.phone = None

        if self.clinic_address and not str(self.clinic_address).strip():
            raise ValidationError({"clinic_address": _("Clinic address cannot be blank spaces.")})

        theme_fields = (
            "primary_color",
            "accent_color",
            "prescription_paper_bg",
            "prescription_paper_border",
            "prescription_header_bg",
            "prescription_header_text_color",
            "prescription_header_line_color",
            "prescription_specialty_text_color",
            "prescription_patient_label_color",
            "prescription_patient_value_color",
        )
        for fname in theme_fields:
            val = getattr(self, fname, "") or ""
            try:
                validate_hex_or_blank(val)
            except ValidationError as exc:
                raise ValidationError({fname: _("Enter HEX like #A1B2C3 (or leave blank).")}) from exc

        if self.photo:
            _validate_upload_image(self.photo, field_name="photo", max_mb=2, kind_label="Image")

        if self.cover_photo:
            _validate_upload_image(self.cover_photo, field_name="cover_photo", max_mb=2, kind_label="Image")

        for field_name in (
            "clinic_logo",
            "signature_image",
            "prescription_header_illustration",
            "prescription_watermark",
        ):
            f = getattr(self, field_name, None)
            if not f:
                continue
            _validate_upload_image(f, field_name=field_name, max_mb=2, kind_label="File")

    def save(self, *args, **kwargs):
        update_fields = kwargs.get("update_fields")
        uf = set(update_fields) if update_fields is not None else None

        # ✅ auto-fill: get_full_name ثم username (حتى لا تنكسر بقية الاختبارات)
        if not (self.full_name or "").strip() and getattr(self, "user_id", None):
            auto_name = (self.user.get_full_name() or "").strip()
            if not auto_name:
                auto_name = (getattr(self.user, "username", "") or "").strip()

            if auto_name:
                self.full_name = auto_name
                if uf is not None:
                    uf.add("full_name")
                    kwargs["update_fields"] = sorted(uf)

        self.full_clean()
        return super().save(*args, **kwargs)

    def __str__(self) -> str:
        return (
            self.full_name
            or (self.user.get_full_name() or "").strip()
            or (getattr(self.user, "username", "") or "").strip()
            or f"Doctor #{self.pk}"
        )

    def get_display_name(self) -> str:
        return self.__str__() or _("Doctor")

    def get_absolute_url(self) -> str:
        return reverse("doctor:detail", args=[self.pk])

    @property
    def is_available(self) -> bool:
        return bool(self.available)

    @property
    def experience(self) -> int:
        return int(self.experience_years or 0)

    def get_card_cover_url(self) -> Optional[str]:
        if self.cover_photo and getattr(self.cover_photo, "url", None):
            return self.cover_photo.url
        if self.photo and getattr(self.photo, "url", None):
            return self.photo.url
        if self.specialty_profile and self.specialty_profile.icon and getattr(self.specialty_profile.icon, "url", None):
            return self.specialty_profile.icon.url
        return None

    @property
    def specialty_name(self) -> str:
        if self.specialty_profile_id and self.specialty_profile:
            return self.specialty_profile.name
        return self.specialty or "General"

    @property
    def ar_title(self) -> str:
        return {"doctor_m": "الدكتور", "doctor_f": "الدكتورة", "clinic": "عيادة"}.get(self.entity_type or "doctor_m", "الدكتور")

    @property
    def ar_prefix(self) -> str:
        return {"doctor_m": "د.", "doctor_f": "د.", "clinic": ""}.get(self.entity_type or "doctor_m", "د.")

    def get_prescription_header_asset(self) -> Optional[str]:
        if self.prescription_header_illustration and hasattr(self.prescription_header_illustration, "url"):
            return self.prescription_header_illustration.url
        if self.specialty_profile and self.specialty_profile.icon and hasattr(self.specialty_profile.icon, "url"):
            return self.specialty_profile.icon.url
        return None

    def get_prescription_logo_asset(self) -> Optional[str]:
        if self.clinic_logo and hasattr(self.clinic_logo, "url"):
            return self.clinic_logo.url
        return None

    def get_signature_asset(self) -> Optional[str]:
        if self.signature_image and hasattr(self.signature_image, "url"):
            return self.signature_image.url
        return None

    def get_prescription_watermark_asset(self):
        wm = getattr(self, "prescription_watermark", None)
        if wm and getattr(wm, "url", None):
            return wm

        sp = getattr(self, "specialty_profile", None)
        if sp and getattr(sp, "icon", None) and getattr(sp.icon, "url", None):
            return sp.icon

        return None


# ------------------------------------------------------------------ #
# Doctor Visit
# ------------------------------------------------------------------ #


class DoctorVisit(models.Model):
    appointment = models.OneToOneField(
        "appointments.Appointment",
        on_delete=models.CASCADE,
        related_name="visit",
        verbose_name=_("Appointment"),
    )
    doctor = models.ForeignKey(
        "doctor.Doctor",
        on_delete=models.CASCADE,
        related_name="visits",
        verbose_name=_("Doctor"),
    )
    patient = models.ForeignKey(
        "patient.Patient",
        on_delete=models.CASCADE,
        related_name="visits",
        verbose_name=_("Patient"),
    )

    chief_complaint = models.CharField(max_length=255, verbose_name=_("Chief Complaint"))
    symptoms = models.TextField(verbose_name=_("Symptoms"))

    history = models.TextField(blank=True, default="", verbose_name=_("History"))
    examination = models.TextField(blank=True, default="", verbose_name=_("Examination"))

    preliminary_diagnosis = models.CharField(max_length=255, blank=True, default="", verbose_name=_("Preliminary Diagnosis"))
    final_diagnosis = models.CharField(max_length=255, blank=True, default="", verbose_name=_("Final Diagnosis"))

    plan = models.TextField(blank=True, default="", verbose_name=_("Plan / Notes"))

    created_at = models.DateTimeField(default=timezone.now, verbose_name=_("Created At"))
    updated_at = models.DateTimeField(auto_now=True, verbose_name=_("Updated At"))

    class Meta:
        verbose_name = _("Doctor Visit")
        verbose_name_plural = _("Doctor Visits")
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["doctor", "created_at"]),
            models.Index(fields=["patient", "created_at"]),
        ]

    def clean(self):
        super().clean()

        self.chief_complaint = _normalize_spaces(self.chief_complaint)
        self.symptoms = _normalize_blankable_str(self.symptoms)
        self.history = _normalize_blankable_str(self.history)
        self.examination = _normalize_blankable_str(self.examination)
        self.preliminary_diagnosis = _normalize_blankable_str(self.preliminary_diagnosis)
        self.final_diagnosis = _normalize_blankable_str(self.final_diagnosis)
        self.plan = _normalize_blankable_str(self.plan)

        if not self.chief_complaint:
            raise ValidationError({"chief_complaint": _("Chief complaint cannot be blank.")})
        if not self.symptoms:
            raise ValidationError({"symptoms": _("Symptoms cannot be blank.")})

        appt = getattr(self, "appointment", None)
        if appt:
            if self.doctor_id and getattr(appt, "doctor_id", None) and self.doctor_id != appt.doctor_id:
                raise ValidationError({"doctor": _("Visit doctor must match the appointment doctor.")})
            if self.patient_id and getattr(appt, "patient_id", None) and self.patient_id != appt.patient_id:
                raise ValidationError({"patient": _("Visit patient must match the appointment patient.")})

    def save(self, *args, **kwargs):
        skip_full_clean = bool(kwargs.pop("skip_full_clean", False))
        if not skip_full_clean:
            self.full_clean()
        return super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"Visit #{self.pk} (Appt #{self.appointment_id})"


# ------------------------------------------------------------------ #
# Doctor Reviews
# ------------------------------------------------------------------ #


class DoctorReview(models.Model):
    doctor = models.ForeignKey(
        "doctor.Doctor",
        on_delete=models.CASCADE,
        related_name="reviews",
        verbose_name=_("Doctor"),
        db_index=True,
    )

    reviewer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="doctor_reviews",
        verbose_name=_("Reviewer"),
        db_index=True,
    )

    rating = models.PositiveSmallIntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(5)],
        verbose_name=_("Rating"),
        help_text=_("1 to 5 stars."),
        db_index=True,
    )

    comment = models.TextField(blank=True, default="", verbose_name=_("Comment"))

    created_at = models.DateTimeField(auto_now_add=True, verbose_name=_("Created At"))
    updated_at = models.DateTimeField(auto_now=True, verbose_name=_("Updated At"))

    class Meta:
        verbose_name = _("Doctor Review")
        verbose_name_plural = _("Doctor Reviews")
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["doctor", "created_at"]),
            models.Index(fields=["doctor", "rating"]),
            models.Index(fields=["reviewer", "created_at"]),
        ]
        constraints = [
            models.CheckConstraint(
                check=models.Q(rating__gte=1) & models.Q(rating__lte=5),
                name="doctorreview_rating_between_1_and_5",
            ),
        ]

    def clean(self):
        super().clean()
        self.comment = _normalize_blankable_str(self.comment)

    def __str__(self) -> str:
        return f"Review({self.doctor_id}) ★{self.rating}"

    def _touch_doctor_cache(self) -> None:
        doctor_id = self.doctor_id
        if not doctor_id:
            return

        def _update():
            Doctor.update_rating_cache_for(doctor_id)

        transaction.on_commit(_update)

    def save(self, *args, **kwargs):
        skip_full_clean = bool(kwargs.pop("skip_full_clean", False))
        if not skip_full_clean:
            self.full_clean()

        res = super().save(*args, **kwargs)
        self._touch_doctor_cache()
        return res

    def delete(self, *args, **kwargs):
        doctor_id = self.doctor_id
        res = super().delete(*args, **kwargs)
        if doctor_id:
            transaction.on_commit(lambda: Doctor.update_rating_cache_for(doctor_id))
        return res