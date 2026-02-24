# medical_archive/models.py
from __future__ import annotations

import logging
import mimetypes
import os
import uuid

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.validators import FileExtensionValidator
from django.db import models
from django.db.models.signals import post_delete
from django.dispatch import receiver
from django.template.defaultfilters import filesizeformat
from django.urls import reverse
from django.utils import timezone
from django.utils.html import format_html, mark_safe
from django.utils.translation import gettext_lazy as _

User = get_user_model()
logger = logging.getLogger(__name__)

# ------------------------------------------------------------
# Constants
# ------------------------------------------------------------
ATTACHMENT_MAX_MB = 10
VOICE_MAX_MB = 25

# ✅ Added webp (اختياري لكنه شائع جداً)
ATTACHMENT_EXTS = ["pdf", "jpg", "jpeg", "png", "gif", "webp"]
AUDIO_EXTS = ["webm", "ogg", "wav", "mp3", "m4a", "aac"]

ATTACHMENT_ALLOWED_MIMES = {
    # PDF
    "application/pdf",
    "application/x-pdf",
    "application/acrobat",
    "application/vnd.pdf",
    "text/pdf",
    # Images
    "image/jpeg",
    "image/jpg",
    "image/png",
    "image/gif",
    "image/webp",
    # ✅ Legacy/edge-case values some browsers may send
    "image/pjpeg",
    "image/x-png",
}

AUDIO_ALLOWED_MIMES = {
    # webm/ogg (بعض البيئات ترجع video/webm حتى لو صوت فقط)
    "audio/webm",
    "video/webm",
    "audio/ogg",
    "application/ogg",
    # wav
    "audio/wav",
    "audio/x-wav",
    # mp3
    "audio/mpeg",
    "audio/mp3",
    # m4a/aac
    "audio/mp4",
    "audio/x-m4a",
    "audio/aac",
    # ✅ بعض الأجهزة ترجع video/mp4 حتى لو ملف صوت (خصوصاً m4a)
    "video/mp4",
}

# ------------------------------------------------------------
# Helpers
# ------------------------------------------------------------
def _normalized_ext(filename: str, default: str) -> str:
    """
    Normalize file extension.
    Example: "photo.JPG" -> "jpg"
    """
    _base, ext = os.path.splitext(filename or "")
    ext = (ext or "").lstrip(".").lower()
    return ext or default


def _normalized_mime(value) -> str | None:
    """
    Normalize content_type / guessed mimetype and strip parameters like:
    'audio/webm;codecs=opus' -> 'audio/webm'
    """
    mime = getattr(value, "content_type", None)
    if not mime:
        mime, _unused = mimetypes.guess_type(getattr(value, "name", "") or "")
    if not mime:
        return None
    mime = str(mime).split(";")[0].strip().lower()
    return mime or None


def _delete_field_file_and_cleanup_folder(field_file, *, levels_up: int = 1) -> None:
    """
    Delete stored file + try to cleanup empty folders (local storage only).

    levels_up:
      1 -> remove immediate folder
      2 -> remove folder and its parent if empty, etc.
    """
    if not field_file or not getattr(field_file, "name", None):
        return

    name = field_file.name
    storage = field_file.storage

    # ✅ Compute folder path BEFORE delete (safer لبعض الـ storages)
    folder = None
    if hasattr(storage, "path"):
        try:
            folder = os.path.dirname(storage.path(name))
        except Exception:
            folder = None

    # 1) delete file
    try:
        storage.delete(name)
    except Exception as e:
        logger.warning("Error deleting stored file %s: %s", name, e)
        return

    # 2) cleanup folders only if we have a local filesystem folder
    if not folder:
        return

    current = folder
    for _ in range(max(0, int(levels_up))):
        try:
            if os.path.isdir(current) and not os.listdir(current):
                os.rmdir(current)
            else:
                break
        except Exception:
            break
        current = os.path.dirname(current)


# ------------------------------------------------------------
# Upload paths
# ------------------------------------------------------------
def archive_file_path(instance, filename: str) -> str:
    """
    مسار حفظ مرفقات الصور/PDF داخل مجلد خاص بكل سجل أرشيف.
    مثال:
      patient_archives/<archive_id>/<uuid>.<ext>
    """
    ext = _normalized_ext(filename, "bin")

    archive_id = getattr(instance, "archive_id", None)
    if not archive_id:
        archive_obj = getattr(instance, "archive", None)
        archive_id = getattr(archive_obj, "pk", None)

    if not archive_id:
        # هذا مفروض ما يصير لأن clean() يمنعه، لكن نخلي fallback آمن
        archive_id = "tmp"
        logger.warning("ArchiveAttachment saved without archive_id. Falling back to tmp path.")

    return f"patient_archives/{archive_id}/{uuid.uuid4()}.{ext}"


def archive_voice_path(instance, filename: str) -> str:
    """
    مسار حفظ التسجيلات الصوتية داخل مجلد خاص بكل سجل أرشيف.
    مثال:
      patient_archives/<archive_id>/voice_notes/<uuid>.<ext>
    """
    ext = _normalized_ext(filename, "webm")

    archive_id = getattr(instance, "archive_id", None)
    if not archive_id:
        archive_obj = getattr(instance, "archive", None)
        archive_id = getattr(archive_obj, "pk", None)

    if not archive_id:
        archive_id = "tmp"
        logger.warning("ArchiveVoiceNote saved without archive_id. Falling back to tmp path.")

    return f"patient_archives/{archive_id}/voice_notes/{uuid.uuid4()}.{ext}"


# ------------------------------------------------------------
# Validators (Attachments: PDF/Images)
# ------------------------------------------------------------
def validate_file_size(value) -> None:
    """منع رفع ملفات أكبر من 10MB للمرفقات (صور/PDF)."""
    max_bytes = ATTACHMENT_MAX_MB * 1024 * 1024
    if getattr(value, "size", 0) > max_bytes:
        raise ValidationError(_("Max file size is %(limit)dMB."), params={"limit": ATTACHMENT_MAX_MB})


def validate_file_mimetype(value) -> None:
    """
    السماح فقط بالأنواع: PDF / Images
    ✅ إذا MIME غير موجود أو octet-stream نعتمد على الامتداد (والامتداد عليه Validator أيضاً).
    """
    mime = _normalized_mime(value)
    if not mime or mime == "application/octet-stream":
        return
    if mime not in ATTACHMENT_ALLOWED_MIMES:
        raise ValidationError(_("File type not allowed (PDF, JPG, PNG, GIF, WEBP only)."))


# ------------------------------------------------------------
# Validators (Voice Notes)
# ------------------------------------------------------------
def validate_audio_file_size(value) -> None:
    """منع رفع ملفات صوت أكبر من 25MB (صوت الطبيب)."""
    max_bytes = VOICE_MAX_MB * 1024 * 1024
    if getattr(value, "size", 0) > max_bytes:
        raise ValidationError(_("Max audio size is %(limit)dMB."), params={"limit": VOICE_MAX_MB})


def validate_audio_mimetype(value) -> None:
    """
    السماح بتسجيلات صوتية فقط.
    ✅ إذا MIME غير متوفر/Octet-stream نعتمد على الامتداد (والامتداد عليه Validator أيضاً).
    """
    mime = _normalized_mime(value)
    if not mime or mime == "application/octet-stream":
        return
    if mime not in AUDIO_ALLOWED_MIMES:
        raise ValidationError(_("Audio type not allowed (webm/ogg/wav/mp3/m4a/aac only)."))


# ------------------------------------------------------------
# Models
# ------------------------------------------------------------
class PatientArchive(models.Model):
    """
    سجل أرشيف طبي عام للمريض:
    يمكن أن يرتبط بزيارة / تحليل / أشعة / وصفة إلكترونية / غيرها.
    """

    ARCHIVE_TYPES = [
        ("visit", _("Visit")),
        ("lab", _("Lab Result")),
        ("scan", _("Scan")),
        ("prescription", _("Prescription")),
        ("other", _("Other")),
    ]

    STATUS_CHOICES = [
        ("draft", _("Draft")),
        ("final", _("Final")),
        ("cancelled", _("Cancelled")),
    ]

    patient = models.ForeignKey(
        "patient.Patient",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,  # ✅ يسمح drafts بدون مريض، لكن clean() يمنعه إذا status != draft
        related_name="medical_archives",
        verbose_name=_("Patient"),
        db_index=True,
    )

    doctor = models.ForeignKey(
        "doctor.Doctor",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,  # ✅ يسمح drafts بدون طبيب، لكن clean() يمنعه إذا status != draft
        related_name="medical_patient_archives",
        verbose_name=_("Doctor"),
        db_index=True,
    )

    appointment = models.ForeignKey(
        "appointments.Appointment",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="archives",
        verbose_name=_("Appointment"),
        help_text=_("Related appointment for this archive (if any)."),
        db_index=True,
    )

    prescription = models.OneToOneField(
        "prescription.Prescription",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="archive_entry",
        verbose_name=_("Prescription"),
        help_text=_("Linked electronic prescription (if any)."),
    )

    title = models.CharField(max_length=255, verbose_name=_("Title"))
    notes = models.TextField(blank=True, verbose_name=_("Notes"))

    archive_type = models.CharField(
        max_length=50,
        choices=ARCHIVE_TYPES,
        default="visit",
        verbose_name=_("Archive Type"),
        db_index=True,
    )

    is_critical = models.BooleanField(default=False, verbose_name=_("Is Critical?"), db_index=True)

    summary_report = models.TextField(
        blank=True,
        help_text=_("Short summary for fast reports"),
        verbose_name=_("Summary Report"),
    )

    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default="final",
        verbose_name=_("Status"),
        db_index=True,
    )

    created_at = models.DateTimeField(default=timezone.now, verbose_name=_("Created At"), db_index=True)
    updated_at = models.DateTimeField(auto_now=True, verbose_name=_("Updated At"))

    created_by = models.ForeignKey(
        User,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="archives_created",
        verbose_name=_("Created By"),
        db_index=True,
    )

    updated_by = models.ForeignKey(
        User,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="archives_updated",
        verbose_name=_("Updated By"),
        db_index=True,
    )

    class Meta:
        ordering = ["-created_at"]
        verbose_name = _("Patient Archive")
        verbose_name_plural = _("Patient Archives")

    def __str__(self) -> str:
        patient_name = getattr(self.patient, "full_name", None) or _("Unknown patient")
        return f"{patient_name} - {self.title} ({self.get_archive_type_display()})"

    # ✅✅✅ ADDED: required-fields business rules (fixes failing tests)
    def clean(self):
        super().clean()

        errors: dict[str, str] = {}

        # Title: حتى لو مسافات فقط
        if not (self.title or "").strip():
            errors["title"] = _("Title is required.")

        # ✅ قواعد العمل: final/cancelled لازم يحتوي patient + doctor
        if self.status != "draft":
            if not self.patient_id:
                errors["patient"] = _("Patient is required for final archives.")
            if not self.doctor_id:
                errors["doctor"] = _("Doctor is required for final archives.")

        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        """
        ✅ Ensure model validation runs even when saving outside ModelForm.
        You can bypass by passing: clean=False
        """
        clean = kwargs.pop("clean", True)
        if clean:
            self.full_clean()
        return super().save(*args, **kwargs)

    def get_color_tag(self) -> str:
        color_map = {
            "visit": "primary",
            "lab": "success",
            "scan": "warning",
            "prescription": "info",
            "other": "secondary",
        }
        return color_map.get(self.archive_type, "secondary")

    def get_absolute_url(self) -> str:
        # ✅ أغلب مشاريعج تستخدم archive_id بالـ kwargs
        try:
            return reverse("medical_archive:archive_detail", kwargs={"archive_id": self.pk})
        except Exception:
            return reverse("medical_archive:archive_detail", args=[self.pk])


class ArchiveAttachment(models.Model):
    """مرفقات السجل (نتائج تحاليل، صور أشعة، PDF للوصفة، إلخ)."""

    archive = models.ForeignKey(
        PatientArchive,
        on_delete=models.CASCADE,
        related_name="attachments",
        verbose_name=_("Archive"),
        db_index=True,
    )

    file = models.FileField(
        upload_to=archive_file_path,
        validators=[
            FileExtensionValidator(ATTACHMENT_EXTS),
            validate_file_size,
            validate_file_mimetype,
        ],
        verbose_name=_("File"),
    )

    description = models.CharField(max_length=500, blank=True, verbose_name=_("Description"))
    uploaded_at = models.DateTimeField(auto_now_add=True, verbose_name=_("Uploaded At"), db_index=True)

    uploaded_by = models.ForeignKey(
        User,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="attachments_uploaded",
        verbose_name=_("Uploaded By"),
        db_index=True,
    )

    # ✅ Needed by tests/admin preview
    IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".gif", ".webp")

    class Meta:
        ordering = ["-uploaded_at"]
        verbose_name = _("Attachment")
        verbose_name_plural = _("Attachments")

    def __str__(self) -> str:
        return f"{self.filename} - {self.description or _('No description')}"

    def save(self, *args, **kwargs):
        """
        ✅ Forces validation on save (prevents silently saving invalid files).
        You can bypass by passing: clean=False
        """
        clean = kwargs.pop("clean", True)
        if clean:
            self.full_clean()
        return super().save(*args, **kwargs)

    def clean(self):
        """منع رفع مرفق إذا الأرشيف غير محفوظ بعد."""
        super().clean()
        if self.archive_id is None:
            raise ValidationError(_("Archive must be saved before uploading attachments."))

    @property
    def filename(self) -> str:
        return os.path.basename(getattr(self.file, "name", "") or "") or "-"

    def is_image(self) -> bool:
        name = (getattr(self.file, "name", "") or "").lower()
        return name.endswith(self.IMAGE_EXTS)

    def is_pdf(self) -> bool:
        name = (getattr(self.file, "name", "") or "").lower()
        return name.endswith(".pdf")

    def file_size(self) -> str:
        try:
            return filesizeformat(self.file.size)
        except Exception:
            return "-"

    def image_tag(self) -> str:
        """
        ✅ HTML preview for admin/tests. Returns '-' for non-images.
        (Tests expect this method to exist.)
        """
        if not getattr(self, "file", None) or not getattr(self.file, "name", None):
            return "-"
        if not self.is_image():
            return "-"

        try:
            url = self.file.url
        except Exception:
            return "-"

        return format_html(
            '<img src="{}" style="max-height:120px;max-width:200px;border-radius:8px;" />',
            url,
        )

    image_tag.short_description = "Preview"

    def preview_html(self):
        """Preview HTML (تستخدم بالـ admin كـ readonly_field)."""
        return self.image_tag()


class ArchiveVoiceNote(models.Model):
    """
    ✅ أرشفة صوتية (ملاحظات الطبيب بالصوت).
    Model منفصل حتى نطبق Validators خاصة بالصوت.
    """

    archive = models.ForeignKey(
        PatientArchive,
        on_delete=models.CASCADE,
        related_name="voice_notes",
        verbose_name=_("Archive"),
        db_index=True,
    )

    audio = models.FileField(
        upload_to=archive_voice_path,
        validators=[
            FileExtensionValidator(AUDIO_EXTS),
            validate_audio_file_size,
            validate_audio_mimetype,
        ],
        verbose_name=_("Audio"),
        help_text=_("Doctor voice note (webm/ogg/wav/mp3/m4a/aac)."),
    )

    title = models.CharField(max_length=200, blank=True, verbose_name=_("Title"))
    duration_seconds = models.PositiveIntegerField(null=True, blank=True, verbose_name=_("Duration (seconds)"))

    recorded_at = models.DateTimeField(default=timezone.now, verbose_name=_("Recorded At"), db_index=True)

    recorded_by = models.ForeignKey(
        User,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="voice_notes_recorded",
        verbose_name=_("Recorded By"),
        db_index=True,
    )

    class Meta:
        ordering = ["-recorded_at"]
        verbose_name = _("Voice Note")
        verbose_name_plural = _("Voice Notes")

    def __str__(self) -> str:
        return self.title or self.filename or _("Voice note")

    def save(self, *args, **kwargs):
        """
        ✅ Forces validation on save.
        You can bypass by passing: clean=False
        """
        clean = kwargs.pop("clean", True)
        if clean:
            self.full_clean()
        return super().save(*args, **kwargs)

    def clean(self):
        """منع حفظ صوت إذا الأرشيف غير محفوظ بعد."""
        super().clean()
        if self.archive_id is None:
            raise ValidationError(_("Archive must be saved before adding voice notes."))

    @property
    def filename(self) -> str:
        return os.path.basename(getattr(self.audio, "name", "") or "") or "-"

    def file_size(self) -> str:
        try:
            return filesizeformat(self.audio.size)
        except Exception:
            return "-"

    def audio_player_html(self):
        """Player preview للـ admin أو أي مكان تحتاجه."""
        try:
            url = self.audio.url
        except Exception:
            return "-"

        return mark_safe(
            f'<audio controls preload="metadata" style="width:240px;">'
            f'<source src="{url}">'
            f'{_("Your browser does not support the audio element.")}'
            f"</audio>"
        )


# ------------------------------------------------------------
# Signals (delete files from storage)
# ------------------------------------------------------------
@receiver(post_delete, sender=ArchiveAttachment)
def delete_attachment_file(sender, instance, **kwargs):
    """عند حذف المرفق من قاعدة البيانات يتم حذف الملف من الـ Storage."""
    _delete_field_file_and_cleanup_folder(getattr(instance, "file", None), levels_up=1)


@receiver(post_delete, sender=ArchiveVoiceNote)
def delete_voice_file(sender, instance, **kwargs):
    """عند حذف الصوت من قاعدة البيانات يتم حذف الملف من الـ Storage."""
    _delete_field_file_and_cleanup_folder(getattr(instance, "audio", None), levels_up=2)
