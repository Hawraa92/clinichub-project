import os

from django import forms
from django.conf import settings

from .models import ECGFile, ECGRecord


DEFAULT_ECG_MAX_UPLOAD_BYTES = 50 * 1024 * 1024

ECG_ALLOWED_EXTENSIONS = {
    ECGFile.FileKind.RAW_SIGNAL: {
        ".dat",
        ".edf",
    },
    ECGFile.FileKind.REPORT_PDF: {
        ".pdf",
    },
    ECGFile.FileKind.IMAGE: {
        ".jpg",
        ".jpeg",
        ".png",
    },
    ECGFile.FileKind.XML: {
        ".xml",
    },
    ECGFile.FileKind.DICOM: {
        ".dcm",
        ".dicom",
    },
    ECGFile.FileKind.WFDB: {
        ".hea",
        ".dat",
    },
    ECGFile.FileKind.CSV: {
        ".csv",
    },
}


class ECGRecordForm(forms.ModelForm):
    class Meta:
        model = ECGRecord

        fields = [
            "patient",
            "doctor",
            "appointment",
            "hospital",
            "branch",
            "department",
            "recorded_at",
            "device_manufacturer",
            "device_model",
            "sampling_frequency_hz",
            "lead_count",
            "duration_seconds",
            "notes",
        ]

        widgets = {
            "patient": forms.Select(
                attrs={
                    "class": "form-select",
                }
            ),
            "doctor": forms.Select(
                attrs={
                    "class": "form-select",
                }
            ),
            "appointment": forms.Select(
                attrs={
                    "class": "form-select",
                }
            ),
            "hospital": forms.Select(
                attrs={
                    "class": "form-select",
                }
            ),
            "branch": forms.Select(
                attrs={
                    "class": "form-select",
                }
            ),
            "department": forms.Select(
                attrs={
                    "class": "form-select",
                }
            ),
            "recorded_at": forms.DateTimeInput(
                format="%Y-%m-%dT%H:%M",
                attrs={
                    "class": "form-control",
                    "type": "datetime-local",
                },
            ),
            "device_manufacturer": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "Device manufacturer",
                }
            ),
            "device_model": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "Device model",
                }
            ),
            "sampling_frequency_hz": forms.NumberInput(
                attrs={
                    "class": "form-control",
                    "min": "1",
                }
            ),
            "lead_count": forms.NumberInput(
                attrs={
                    "class": "form-control",
                    "min": "1",
                }
            ),
            "duration_seconds": forms.NumberInput(
                attrs={
                    "class": "form-control",
                    "min": "0",
                    "step": "0.01",
                }
            ),
            "notes": forms.Textarea(
                attrs={
                    "class": "form-control",
                    "rows": 4,
                    "placeholder": "Optional ECG notes",
                }
            ),
        }

    def __init__(
        self,
        *args,
        patient_queryset=None,
        doctor_queryset=None,
        appointment_queryset=None,
        hospital_queryset=None,
        branch_queryset=None,
        department_queryset=None,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)

        self.fields["recorded_at"].input_formats = [
            "%Y-%m-%dT%H:%M",
        ]

        scoped_querysets = {
            "patient": patient_queryset,
            "doctor": doctor_queryset,
            "appointment": appointment_queryset,
            "hospital": hospital_queryset,
            "branch": branch_queryset,
            "department": department_queryset,
        }

        for field_name, queryset in scoped_querysets.items():
            if queryset is None:
                self.fields[field_name].queryset = (
                    self.fields[field_name]
                    .queryset
                    .none()
                )
            else:
                self.fields[field_name].queryset = queryset

        self.fields["appointment"].required = False
        self.fields["hospital"].required = False
        self.fields["branch"].required = False
        self.fields["department"].required = False


class ECGFileForm(forms.ModelForm):
    class Meta:
        model = ECGFile

        fields = [
            "kind",
            "file",
        ]

        widgets = {
            "kind": forms.Select(
                attrs={
                    "class": "form-select",
                }
            ),
            "file": forms.FileInput(
                attrs={
                    "class": "form-control",
                }
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        supported_kinds = {
            ECGFile.FileKind.RAW_SIGNAL,
            ECGFile.FileKind.REPORT_PDF,
            ECGFile.FileKind.IMAGE,
            ECGFile.FileKind.XML,
            ECGFile.FileKind.DICOM,
            ECGFile.FileKind.WFDB,
            ECGFile.FileKind.CSV,
        }

        self.fields["kind"].choices = [
            choice
            for choice in ECGFile.FileKind.choices
            if choice[0] in supported_kinds
        ]

        max_upload_bytes = getattr(
            settings,
            "ECG_MAX_UPLOAD_BYTES",
            DEFAULT_ECG_MAX_UPLOAD_BYTES,
        )

        max_upload_mb = max_upload_bytes // (
            1024 * 1024
        )

        self.fields["file"].help_text = (
            f"Maximum file size: {max_upload_mb} MB."
        )

    def clean_file(self):
        uploaded_file = self.cleaned_data.get("file")

        if uploaded_file is None:
            return uploaded_file

        if uploaded_file.size <= 0:
            raise forms.ValidationError(
                "The uploaded ECG file is empty."
            )

        max_upload_bytes = getattr(
            settings,
            "ECG_MAX_UPLOAD_BYTES",
            DEFAULT_ECG_MAX_UPLOAD_BYTES,
        )

        if uploaded_file.size > max_upload_bytes:
            max_upload_mb = max_upload_bytes // (
                1024 * 1024
            )

            raise forms.ValidationError(
                f"The ECG file must not exceed "
                f"{max_upload_mb} MB."
            )

        filename = os.path.basename(
            uploaded_file.name
        )

        if not filename:
            raise forms.ValidationError(
                "The uploaded file must have a valid name."
            )

        extension = os.path.splitext(
            filename
        )[1].lower()

        if not extension:
            raise forms.ValidationError(
                "The uploaded ECG file must have "
                "a recognized file extension."
            )

        return uploaded_file

    def clean(self):
        cleaned_data = super().clean()

        uploaded_file = cleaned_data.get("file")
        kind = cleaned_data.get("kind")

        if uploaded_file is None or not kind:
            return cleaned_data

        extension = os.path.splitext(
            os.path.basename(uploaded_file.name)
        )[1].lower()

        allowed_extensions = ECG_ALLOWED_EXTENSIONS.get(
            kind,
            set(),
        )

        if extension not in allowed_extensions:
            allowed_text = ", ".join(
                sorted(allowed_extensions)
            )

            self.add_error(
                "file",
                (
                    "This file type does not match the "
                    f"selected ECG file kind. Allowed: "
                    f"{allowed_text}."
                ),
            )

        return cleaned_data