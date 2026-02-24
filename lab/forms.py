# lab/forms.py
from __future__ import annotations

import os
from typing import Optional

from django import forms

from .models import LabOrder, LabResult, LabSettings


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
            "doctor_attachment",  # ✅ NEW
        ]
        widgets = {
            "requested_tests_text": forms.Textarea(
                attrs={
                    "rows": 4,
                    "placeholder": "e.g. CBC + CRP + ESR",
                }
            ),
            "notes": forms.Textarea(
                attrs={
                    "rows": 3,
                    "placeholder": "Notes for lab (optional)",
                }
            ),
            # ✅ Improves UX: shows only PDF in file picker (still validated server-side)
            "doctor_attachment": forms.ClearableFileInput(
                attrs={"accept": "application/pdf"}
            ),
        }

    def clean_doctor_attachment(self):
        """
        Extra safety:
        - Enforce PDF extension (in addition to model validator)
        - Enforce size limit using LabSettings.max_upload_mb
        """
        f = self.cleaned_data.get("doctor_attachment")
        if not f:
            return f

        # Ensure settings exists
        settings_obj = LabSettings.get_solo()

        # Size check
        try:
            max_mb = int(getattr(settings_obj, "max_upload_mb", 10))
        except (TypeError, ValueError):
            max_mb = 10

        max_bytes = max_mb * 1024 * 1024
        if getattr(f, "size", 0) and f.size > max_bytes:
            raise forms.ValidationError(f"PDF is too large. Max allowed is {max_mb} MB.")

        # Type check (extension-based)
        ext = os.path.splitext((f.name or "").lower())[1]
        if ext != ".pdf":
            raise forms.ValidationError("Only PDF files are allowed.")

        # If lab settings disables PDFs, respect it
        allow_pdf = bool(getattr(settings_obj, "allow_pdf", True))
        if not allow_pdf:
            raise forms.ValidationError("PDF uploads are disabled by Lab settings.")

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

        # Prefill default template if available and result_text is empty
        if not self.settings_obj:
            self.settings_obj = LabSettings.get_solo()

        default_tpl = (getattr(self.settings_obj, "default_result_template", "") or "").strip()
        current_text = (getattr(self.instance, "result_text", "") or "").strip()

        if default_tpl and not current_text:
            self.fields["result_text"].initial = default_tpl

    class Meta:
        model = LabResult
        fields = ["result_text", "attachment"]
        widgets = {
            "result_text": forms.Textarea(
                attrs={
                    "rows": 6,
                    "placeholder": "Enter result summary or notes...",
                }
            ),
        }

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
        try:
            max_mb = int(getattr(settings_obj, "max_upload_mb", 10))
        except (TypeError, ValueError):
            max_mb = 10

        max_bytes = max_mb * 1024 * 1024
        if getattr(file, "size", 0) and file.size > max_bytes:
            raise forms.ValidationError(f"File is too large. Max allowed is {max_mb} MB.")

        # Type check (extension-based)
        ext = os.path.splitext((file.name or "").lower())[1]
        allow_pdf = bool(getattr(settings_obj, "allow_pdf", True))
        allow_images = bool(getattr(settings_obj, "allow_images", True))

        if ext in self.PDF_EXTS and not allow_pdf:
            raise forms.ValidationError("PDF uploads are disabled by Lab settings.")
        if ext in self.IMAGE_EXTS and not allow_images:
            raise forms.ValidationError("Image uploads are disabled by Lab settings.")

        allowed = set()
        if allow_pdf:
            allowed |= self.PDF_EXTS
        if allow_images:
            allowed |= self.IMAGE_EXTS

        if ext not in allowed:
            allowed_str = ", ".join(sorted(allowed)) or "None"
            raise forms.ValidationError(f"File type not allowed. Allowed: {allowed_str}")

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
