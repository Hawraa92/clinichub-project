# lab/forms.py
from __future__ import annotations

import os
from typing import Optional

from django import forms

from .models import LabOrder, LabResult, LabSettings


def _safe_int(val, default: int) -> int:
    try:
        return int(val)
    except Exception:
        return default


def _file_ext(file_obj) -> str:
    return os.path.splitext((getattr(file_obj, "name", "") or "").lower())[1]


def _file_too_big(file_obj, max_mb: int) -> bool:
    max_bytes = max(1, max_mb) * 1024 * 1024
    size = getattr(file_obj, "size", 0) or 0
    return size > max_bytes


def _best_effort_is_pdf(file_obj) -> bool:
    """
    Best-effort check based on content_type if provided.
    لا نعتمد عليه وحده لأن بعض السيرفرات/البراوزرات ترجع application/octet-stream
    """
    ct = (getattr(file_obj, "content_type", "") or "").lower().strip()
    if not ct:
        return True
    return ("pdf" in ct) or (ct == "application/pdf") or (ct == "application/octet-stream")


def _best_effort_is_image(file_obj) -> bool:
    ct = (getattr(file_obj, "content_type", "") or "").lower().strip()
    if not ct:
        return True
    return ct.startswith("image/") or (ct == "application/octet-stream")


class LabOrderCreateForm(forms.ModelForm):
    """
    Doctor creates a lab order.
    ✅ Supports optional PDF attachment from doctor (doctor_attachment).
    """

    class Meta:
        model = LabOrder
        fields = [
            "appointment",
            "requested_tests_text",
            "urgency",
            "notes",
            "doctor_attachment",
        ]
        widgets = {
            "requested_tests_text": forms.Textarea(
                attrs={"rows": 4, "placeholder": "e.g. CBC + CRP + ESR"}
            ),
            "notes": forms.Textarea(
                attrs={"rows": 3, "placeholder": "Notes for lab (optional)"}
            ),
            "doctor_attachment": forms.ClearableFileInput(
                attrs={"accept": "application/pdf"}
            ),
        }

    def clean_requested_tests_text(self):
        v = (self.cleaned_data.get("requested_tests_text") or "").strip()
        if not v:
            raise forms.ValidationError("Requested tests cannot be empty.")
        return v

    def clean_notes(self):
        v = self.cleaned_data.get("notes")
        if v is None:
            return v
        return (v or "").strip()

    def clean_doctor_attachment(self):
        """
        Extra safety:
        - Enforce PDF extension (in addition to model validator)
        - Enforce size limit using LabSettings.max_upload_mb
        - Respect LabSettings.allow_pdf
        """
        f = self.cleaned_data.get("doctor_attachment")
        if not f:
            return f

        settings_obj = LabSettings.get_solo()

        # Size check
        max_mb = _safe_int(getattr(settings_obj, "max_upload_mb", 10), 10)
        if _file_too_big(f, max_mb):
            raise forms.ValidationError(f"PDF is too large. Max allowed is {max_mb} MB.")

        # If lab settings disables PDFs, respect it
        allow_pdf = bool(getattr(settings_obj, "allow_pdf", True))
        if not allow_pdf:
            raise forms.ValidationError("PDF uploads are disabled by Lab settings.")

        # Extension-based type check
        ext = _file_ext(f)
        if ext != ".pdf":
            raise forms.ValidationError("Only PDF files are allowed.")

        # Best-effort MIME check (doesn't block octet-stream)
        if not _best_effort_is_pdf(f):
            raise forms.ValidationError("Uploaded file does not look like a PDF.")

        return f


class LabResultForm(forms.ModelForm):
    """
    Lab result form with settings-aware validation:
    - max upload size (max_upload_mb)
    - allow_pdf / allow_images
    - optional default_result_template prefilling (if result_text empty)
    """

    IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp"}
    PDF_EXTS = {".pdf"}

    def __init__(self, *args, **kwargs):
        self.settings_obj: Optional[LabSettings] = kwargs.pop("settings_obj", None)
        super().__init__(*args, **kwargs)

        if not self.settings_obj:
            self.settings_obj = LabSettings.get_solo()

        default_tpl = (getattr(self.settings_obj, "default_result_template", "") or "").strip()
        current_text = (getattr(self.instance, "result_text", "") or "").strip()

        # Prefill only when instance has no text (won't override bound POST)
        if default_tpl and not current_text:
            self.fields["result_text"].initial = default_tpl

    class Meta:
        model = LabResult
        fields = ["result_text", "attachment"]
        widgets = {
            "result_text": forms.Textarea(
                attrs={"rows": 6, "placeholder": "Enter result summary or notes..."}
            ),
        }

    def clean_result_text(self):
        v = self.cleaned_data.get("result_text")
        if v is None:
            return v
        return (v or "").strip()

    def clean_attachment(self):
        """
        Validate attachment using LabSettings:
        - size limit (max_upload_mb)
        - allowed file types (PDF/images)
        """
        file = self.cleaned_data.get("attachment")
        if not file:
            return file

        settings_obj = self.settings_obj or LabSettings.get_solo()

        # Size check
        max_mb = _safe_int(getattr(settings_obj, "max_upload_mb", 10), 10)
        if _file_too_big(file, max_mb):
            raise forms.ValidationError(f"File is too large. Max allowed is {max_mb} MB.")

        # Allowed types
        ext = _file_ext(file)
        allow_pdf = bool(getattr(settings_obj, "allow_pdf", True))
        allow_images = bool(getattr(settings_obj, "allow_images", True))

        allowed = set()
        if allow_pdf:
            allowed |= self.PDF_EXTS
        if allow_images:
            allowed |= self.IMAGE_EXTS

        if ext not in allowed:
            allowed_str = ", ".join(sorted(allowed)) or "None"
            raise forms.ValidationError(f"File type not allowed. Allowed: {allowed_str}")

        # Best-effort content_type checks
        if ext in self.PDF_EXTS and not _best_effort_is_pdf(file):
            raise forms.ValidationError("Uploaded file does not look like a PDF.")
        if ext in self.IMAGE_EXTS and not _best_effort_is_image(file):
            raise forms.ValidationError("Uploaded file does not look like an image.")

        return file


class LabSettingsForm(forms.ModelForm):
    class Meta:
        model = LabSettings
        fields = [
            "lab_name",
            "lab_phone",
            "lab_address",
            "lab_logo",
            "max_upload_mb",
            "allow_pdf",
            "allow_images",
            "require_verify_before_ready",
            "default_result_template",
            "footer_note",
        ]
        widgets = {
            "lab_name": forms.TextInput(attrs={"placeholder": "ClinicHub Lab"}),
            "lab_phone": forms.TextInput(attrs={"placeholder": "+964 ..."}),
            "lab_address": forms.TextInput(attrs={"placeholder": "Baghdad, ..."}),
            "max_upload_mb": forms.NumberInput(attrs={"min": 1, "max": 200}),
            "default_result_template": forms.Textarea(attrs={"rows": 4}),
            "footer_note": forms.TextInput(attrs={"placeholder": "Optional footer note..."}),
        }

    def clean_lab_name(self):
        return (self.cleaned_data.get("lab_name") or "").strip()

    def clean_lab_phone(self):
        v = self.cleaned_data.get("lab_phone")
        return (v or "").strip()

    def clean_lab_address(self):
        v = self.cleaned_data.get("lab_address")
        return (v or "").strip()

    def clean_max_upload_mb(self):
        v = _safe_int(self.cleaned_data.get("max_upload_mb"), 10)
        # enforce sane bounds server-side
        if v < 1:
            raise forms.ValidationError("max_upload_mb must be at least 1 MB.")
        if v > 200:
            raise forms.ValidationError("max_upload_mb is too high (max 200 MB).")
        return v