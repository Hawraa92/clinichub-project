# File: medical_archive/forms.py
from __future__ import annotations

from typing import Any, List, Optional

from django import forms
from django.apps import apps
from django.core.exceptions import ValidationError
from django.core.validators import FileExtensionValidator
from django.utils.translation import gettext_lazy as _

from .models import (
    ArchiveVoiceNote,
    PatientArchive,
    AUDIO_EXTS,
    ATTACHMENT_EXTS,
    validate_audio_file_size,
    validate_audio_mimetype,
    validate_file_mimetype,
    validate_file_size,
)

# ---------------------------------------------------------------------
# OPTIONAL: Only set this if you REALLY use inputs OUTSIDE the <form>
# and you are 100% sure your HTML form has id="medicalRecordForm".
# ---------------------------------------------------------------------
FORM_ID: Optional[str] = None  # e.g. "medicalRecordForm"

# Keep consistent with JS (create_archive.js)
TITLE_MAX_LEN = 200
NOTES_MAX_LEN = 5000
ATTACH_DESC_MAX_LEN = 500
MAX_FILES = 10


def _maybe_add_form_attr(attrs: dict) -> dict:
    """Add HTML 'form' attribute only when FORM_ID is set."""
    if FORM_ID:
        attrs.setdefault("form", FORM_ID)
    return attrs


# ---------------------------------------------------------------------
# Multi-file support (Attachments: PDF/Images)
# ---------------------------------------------------------------------
class MultiFileInput(forms.ClearableFileInput):
    """
    A file input widget that supports selecting multiple files.

    ✅ IMPORTANT:
    value_from_datadict is overridden to ALWAYS return files.getlist(name),
    which fixes cases where only one file (or none) is received.
    """
    allow_multiple_selected = True

    def __init__(self, attrs: Optional[dict] = None):
        # Build accept string from model-allowed extensions
        # Example: ".pdf,.jpg,.jpeg,.png,.gif,.webp"
        accept_str = ",".join(f".{ext}" for ext in (ATTACHMENT_EXTS or []) if ext)

        base_attrs = {
            "class": "form-control form-control-lg",
            "id": "id_files",
            "multiple": True,
            "accept": accept_str or ".pdf,.jpg,.jpeg,.png,.gif",
        }
        if attrs:
            base_attrs.update(attrs)
        super().__init__(attrs=_maybe_add_form_attr(base_attrs))

    def value_from_datadict(self, data, files, name):
        """
        ✅ Force list behavior for multiple uploads.
        """
        if self.allow_multiple_selected:
            try:
                return files.getlist(name)
            except Exception:
                # Fallback to default behavior if files isn't MultiValueDict
                v = super().value_from_datadict(data, files, name)
                return v if isinstance(v, (list, tuple)) else ([v] if v else [])
        return super().value_from_datadict(data, files, name)


class MultiFileField(forms.FileField):
    """
    A FileField that accepts multiple uploaded files and ALWAYS returns a list.

    - Validates each file independently (extension/size/mimetype).
    - Returns [] if no files were uploaded.
    - Enforces a max number of files (server-side).
    """

    def __init__(self, *args, **kwargs):
        kwargs.setdefault("required", False)
        kwargs.setdefault("widget", MultiFileInput())
        super().__init__(*args, **kwargs)

        # ✅ Use the SAME extensions as the model (single source of truth)
        self._per_file_validators = [
            FileExtensionValidator(allowed_extensions=ATTACHMENT_EXTS),
            validate_file_size,
            validate_file_mimetype,
        ]

        # Keep in sync with your JS (MAX_FILES = 10)
        self.max_files = MAX_FILES

    def clean(self, data: Any, initial: Any = None) -> List:
        """Normalize input into a list and validate each file individually."""
        if not data:
            return []

        files = data if isinstance(data, (list, tuple)) else [data]

        # Remove empties early
        files = [f for f in files if f]

        if self.max_files and len(files) > self.max_files:
            raise ValidationError(_("You can upload up to %(n)s files only."), params={"n": self.max_files})

        cleaned_files: List = []
        single_clean = super().clean

        for f in files:
            cleaned = single_clean(f, initial=None)

            for validator in self._per_file_validators:
                validator(cleaned)

            # Safety: rewind pointer if any validator read from it
            try:
                cleaned.seek(0)
            except Exception:
                pass

            cleaned_files.append(cleaned)

        return cleaned_files


# ---------------------------------------------------------------------
# Archive Form (Doctor field REMOVED from UI)
# ---------------------------------------------------------------------
class PatientArchiveForm(forms.ModelForm):
    """
    Form for creating/editing a PatientArchive.

    ✅ Physician/doctor field removed from the form UI.
    ✅ Doctor can be assigned server-side from the logged-in user's doctor profile IF available.

    Important RBAC behavior:
    - If user.role == "doctor": doctor profile MUST exist.
    - If user is admin/secretary/superuser: doctor profile is optional (doctor may stay NULL).
    """

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self._user = user
        self._forced_doctor = None

        # Determine role (safe)
        self._role = getattr(user, "role", None)
        self._is_superuser = bool(getattr(user, "is_superuser", False))
        self._must_have_doctor = (self._role == "doctor")

        # Remove doctor field completely from UI + POST binding
        self.fields.pop("doctor", None)

        # Required fields
        if "patient" in self.fields:
            self.fields["patient"].required = True
            try:
                self.fields["patient"].empty_label = _("Select a patient")
            except Exception:
                pass

        if "archive_type" in self.fields:
            self.fields["archive_type"].required = True

        if "title" in self.fields:
            self.fields["title"].required = True

        # Resolve doctor from user (for save) - optional unless role == doctor
        self._forced_doctor = self._resolve_doctor_from_user(user)

        self._apply_widget_attrs()

    @staticmethod
    def _resolve_doctor_from_user(user):
        """Resolve Doctor instance from the logged-in user without hard imports."""
        if user is None:
            return None

        # 1) If user has a direct related attribute
        for attr in ("doctor", "doctor_profile", "profile_doctor"):
            obj = getattr(user, attr, None)
            if obj is not None:
                return obj

        # 2) Query Doctor by FK user
        try:
            Doctor = apps.get_model("doctor", "Doctor")
            return Doctor.objects.select_related("user").get(user=user)
        except Exception:
            return None

    def _apply_widget_attrs(self) -> None:
        """Apply consistent UI attributes."""
        if "patient" in self.fields:
            self.fields["patient"].widget.attrs.update(
                {
                    "class": "form-select form-select-lg",
                    "id": "id_patient",
                    "data-placeholder": "Select a patient",
                }
            )

        if "title" in self.fields:
            self.fields["title"].widget.attrs.update(
                {
                    "class": "form-control form-control-lg",
                    "id": "id_title",
                    "placeholder": "e.g., Annual Physical Exam, Blood Test Results",
                    "maxlength": str(TITLE_MAX_LEN),
                }
            )

        if "notes" in self.fields:
            self.fields["notes"].widget = forms.Textarea(
                attrs={
                    "rows": 4,
                    "class": "form-control form-control-lg",
                    "id": "id_notes",
                    "placeholder": "Write detailed clinical notes here...",
                    "maxlength": str(NOTES_MAX_LEN),
                }
            )

        if "archive_type" in self.fields:
            self.fields["archive_type"].widget.attrs.update(
                {
                    "class": "form-select form-select-lg",
                    "id": "id_archive_type",
                    "data-placeholder": "Select record type",
                }
            )

        if "is_critical" in self.fields:
            self.fields["is_critical"].widget.attrs.update(
                {
                    "class": "form-check-input",
                    "id": "id_is_critical",
                }
            )

        # Optional: set form attribute only if you really need it
        if FORM_ID:
            for field in self.fields.values():
                try:
                    field.widget.attrs = _maybe_add_form_attr(field.widget.attrs)
                except Exception:
                    pass

    def clean_title(self) -> str:
        """Validate the record title."""
        title = (self.cleaned_data.get("title") or "").strip()

        if len(title) < 5:
            raise forms.ValidationError(_("Title must be at least 5 characters."))

        if len(title) > TITLE_MAX_LEN:
            raise forms.ValidationError(_("Title must be at most %(n)s characters."), params={"n": TITLE_MAX_LEN})

        return title

    def clean(self):
        """
        If creating a NEW record and user is a doctor, we MUST find doctor profile.
        If editing an existing record that already has a doctor, we allow it.
        For admin/secretary/superuser: doctor is optional.
        """
        cleaned = super().clean()

        instance_doctor = getattr(self.instance, "doctor", None)
        if instance_doctor is None and self._forced_doctor is None and self._must_have_doctor:
            raise forms.ValidationError(_("Doctor profile not found for this account."))

        return cleaned

    def save(self, commit: bool = True) -> PatientArchive:
        """Assign doctor server-side (because the field is removed from UI)."""
        obj: PatientArchive = super().save(commit=False)

        if getattr(obj, "doctor", None) is None and self._forced_doctor is not None:
            obj.doctor = self._forced_doctor

        if getattr(obj, "doctor", None) is None and self._must_have_doctor:
            raise ValidationError(_("Doctor profile not found for this account."))

        if commit:
            obj.save()
            self.save_m2m()
        return obj

    class Meta:
        model = PatientArchive
        fields = [
            "patient",
            "title",
            "notes",
            "archive_type",
            "is_critical",
        ]
        labels = {
            "patient": _("Patient"),
            "title": _("Record Title"),
            "notes": _("Clinical Notes"),
            "archive_type": _("Record Type"),
            "is_critical": _("Critical"),
        }


# ---------------------------------------------------------------------
# Attachments Form
# ---------------------------------------------------------------------
class ArchiveAttachmentForm(forms.Form):
    """
    Upload one or more attachments with a single shared description.

    Rules:
    - Files are optional.
    - If files exist, description becomes required.
    """

    files = MultiFileField(
        required=False,
        help_text=_("Select one or more files to attach (max 10MB each)."),
    )

    description = forms.CharField(
        required=False,
        label=_("Attachment Description"),
        max_length=ATTACH_DESC_MAX_LEN,
        widget=forms.TextInput(
            attrs=_maybe_add_form_attr(
                {
                    "class": "form-control form-control-lg",
                    "id": "id_description",
                    "placeholder": "e.g., Chest X-ray, Blood Test PDF",
                    "maxlength": str(ATTACH_DESC_MAX_LEN),
                }
            ),
        ),
    )

    def clean_files(self):
        """MultiFileField already guarantees a list."""
        return self.cleaned_data.get("files") or []

    def clean(self):
        cleaned_data = super().clean()
        files = cleaned_data.get("files") or []
        description = (cleaned_data.get("description") or "").strip()

        if files and not description:
            self.add_error("description", _("Please provide a description when uploading files."))

        return cleaned_data


# ---------------------------------------------------------------------
# Voice Note Form (Audio Upload)
# ---------------------------------------------------------------------
class ArchiveVoiceNoteForm(forms.ModelForm):
    """
    ✅ Upload a doctor voice note (audio) linked to a PatientArchive.

    - audio optional (not every archive needs voice)
    - title optional
    - duration_seconds optional

    ✅ Test expectation:
    - إذا المستخدم كتب Title بدون Audio => الفورم لازم يفشل (is_valid=False)
      حتى الـ view يرجّع نفس الصفحة (status 200) بدل redirect (302).
    """

    audio = forms.FileField(
        required=False,
        label=_("Voice Note"),
        validators=[
            FileExtensionValidator(allowed_extensions=AUDIO_EXTS),
            validate_audio_file_size,
            validate_audio_mimetype,
        ],
        widget=forms.ClearableFileInput(
            attrs=_maybe_add_form_attr(
                {
                    "class": "form-control form-control-lg",
                    "id": "id_voice_audio",
                    "accept": "audio/*,.webm,.ogg,.wav,.mp3,.m4a,.aac",
                }
            )
        ),
        help_text=_("Upload a voice note (webm/ogg/wav/mp3/m4a)."),
    )

    class Meta:
        model = ArchiveVoiceNote
        fields = ["audio", "title", "duration_seconds"]

        widgets = {
            "title": forms.TextInput(
                attrs=_maybe_add_form_attr(
                    {
                        "class": "form-control form-control-lg",
                        "id": "id_voice_title",
                        "placeholder": "e.g., Medication instructions",
                        "maxlength": "200",
                    }
                )
            ),
            "duration_seconds": forms.NumberInput(
                attrs=_maybe_add_form_attr(
                    {
                        "class": "form-control form-control-lg",
                        "id": "id_voice_duration",
                        "min": "0",
                        "placeholder": "Duration (seconds)",
                    }
                )
            ),
        }

    def clean_title(self) -> str:
        title = (self.cleaned_data.get("title") or "").strip()
        if len(title) > TITLE_MAX_LEN:
            raise ValidationError(_("Title must be at most %(n)s characters."), params={"n": TITLE_MAX_LEN})
        return title

    def clean_duration_seconds(self):
        val = self.cleaned_data.get("duration_seconds")
        if val is None or val == "":
            return val
        try:
            val_int = int(val)
        except Exception as exc:
            raise ValidationError(_("Duration must be a number.")) from exc
        if val_int < 0:
            raise ValidationError(_("Duration cannot be negative."))
        return val_int

    def clean(self):
        cleaned = super().clean()

        title = (cleaned.get("title") or "").strip()
        audio = cleaned.get("audio")

        # ✅ IMPORTANT RULE (fixes your failing integration test):
        # If a title is provided, an audio file MUST be provided.
        if title and not audio:
            self.add_error("audio", _("Audio file is required when a title is provided."))

        # Optional strict rule (if you want it later):
        # if audio and not title:
        #     self.add_error("title", _("Please add a title for the voice note."))

        return cleaned