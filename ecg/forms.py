import csv
import os

from django import forms
from django.conf import settings

from .models import ECGFile, ECGRecord


DEFAULT_ECG_MAX_UPLOAD_BYTES = 50 * 1024 * 1024
ECG_CONTENT_SNIFF_BYTES = 64 * 1024

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


DANGEROUS_FILE_SIGNATURES = (
    b"MZ",
    b"\x7fELF",
    b"PK\x03\x04",
    b"Rar!\x1a\x07",
    b"7z\xbc\xaf\x27\x1c",
    b"\x1f\x8b",
)


def read_upload_prefix(uploaded_file):
    try:
        original_position = uploaded_file.tell()
    except (AttributeError, OSError):
        original_position = 0

    try:
        uploaded_file.seek(0)

        return uploaded_file.read(
            ECG_CONTENT_SNIFF_BYTES
        )
    finally:
        uploaded_file.seek(
            original_position
        )


def reject_dangerous_signature(prefix):
    for signature in DANGEROUS_FILE_SIGNATURES:
        if prefix.startswith(signature):
            raise forms.ValidationError(
                "The uploaded file content is not "
                "allowed for an ECG clinical file."
            )


def validate_pdf_content(prefix):
    if not prefix.startswith(b"%PDF-"):
        raise forms.ValidationError(
            "The uploaded file does not contain "
            "a valid PDF signature."
        )


def validate_image_content(prefix, extension):
    if extension == ".png":
        if not prefix.startswith(
            b"\x89PNG\r\n\x1a\n"
        ):
            raise forms.ValidationError(
                "The uploaded file does not contain "
                "a valid PNG signature."
            )

        return

    if extension in {
        ".jpg",
        ".jpeg",
    }:
        if not prefix.startswith(
            b"\xff\xd8\xff"
        ):
            raise forms.ValidationError(
                "The uploaded file does not contain "
                "a valid JPEG signature."
            )

        return

    raise forms.ValidationError(
        "Unsupported ECG image format."
    )


def decode_xml_prefix(prefix):
    try:
        if prefix.startswith(
            (
                b"\xff\xfe",
                b"\xfe\xff",
            )
        ):
            return prefix.decode(
                "utf-16"
            )

        return prefix.decode(
            "utf-8-sig"
        )

    except UnicodeDecodeError as exc:
        raise forms.ValidationError(
            "The XML file must contain valid "
            "UTF-8 or UTF-16 text."
        ) from exc


def validate_xml_content(prefix):
    text = decode_xml_prefix(
        prefix
    )

    stripped_text = text.lstrip()

    if not stripped_text.startswith("<"):
        raise forms.ValidationError(
            "The uploaded file does not appear "
            "to contain XML content."
        )

    upper_text = stripped_text.upper()

    if "<!DOCTYPE" in upper_text:
        raise forms.ValidationError(
            "XML files containing DOCTYPE "
            "declarations are not allowed."
        )

    if "<!ENTITY" in upper_text:
        raise forms.ValidationError(
            "XML files containing entity "
            "declarations are not allowed."
        )


def validate_csv_content(prefix):
    if b"\x00" in prefix:
        raise forms.ValidationError(
            "The uploaded CSV file contains "
            "invalid binary content."
        )

    try:
        text = prefix.decode(
            "utf-8-sig"
        )
    except UnicodeDecodeError as exc:
        raise forms.ValidationError(
            "The CSV file must contain "
            "valid UTF-8 text."
        ) from exc

    sample = text.strip()

    if not sample:
        raise forms.ValidationError(
            "The uploaded CSV file is empty."
        )

    try:
        dialect = csv.Sniffer().sniff(
            sample,
            delimiters=",;\t|",
        )
    except csv.Error as exc:
        raise forms.ValidationError(
            "The uploaded file does not appear "
            "to contain valid tabular CSV data."
        ) from exc

    reader = csv.reader(
        sample.splitlines(),
        dialect,
    )

    try:
        first_row = next(reader)
    except StopIteration as exc:
        raise forms.ValidationError(
            "The uploaded CSV file does not "
            "contain any rows."
        ) from exc

    if len(first_row) < 2:
        raise forms.ValidationError(
            "The uploaded CSV file must contain "
            "at least two columns."
        )


def validate_dicom_content(prefix):
    if len(prefix) < 132:
        raise forms.ValidationError(
            "The uploaded DICOM file is too short "
            "to contain a standard DICOM header."
        )

    if prefix[128:132] != b"DICM":
        raise forms.ValidationError(
            "The uploaded file does not contain "
            "a standard DICOM signature."
        )


def validate_edf_content(prefix):
    if len(prefix) < 256:
        raise forms.ValidationError(
            "The uploaded EDF file is too short "
            "to contain a valid EDF header."
        )

    try:
        version = prefix[:8].decode(
            "ascii"
        )

        header_bytes = prefix[
            168:176
        ].decode(
            "ascii"
        ).strip()

    except UnicodeDecodeError as exc:
        raise forms.ValidationError(
            "The uploaded file does not contain "
            "a valid EDF header."
        ) from exc

    if version.strip() != "0":
        raise forms.ValidationError(
            "The uploaded file does not contain "
            "a recognized EDF version header."
        )

    if (
        not header_bytes
        or not header_bytes.isdigit()
    ):
        raise forms.ValidationError(
            "The uploaded file does not contain "
            "a valid EDF header length."
        )


def validate_wfdb_header_content(prefix):
    if b"\x00" in prefix:
        raise forms.ValidationError(
            "The WFDB header contains "
            "invalid binary content."
        )

    try:
        text = prefix.decode(
            "ascii"
        )
    except UnicodeDecodeError as exc:
        raise forms.ValidationError(
            "The WFDB header must contain "
            "valid ASCII text."
        ) from exc

    first_line = ""

    for line in text.splitlines():
        stripped_line = line.strip()

        if (
            stripped_line
            and not stripped_line.startswith("#")
        ):
            first_line = stripped_line
            break

    if not first_line:
        raise forms.ValidationError(
            "The WFDB header does not contain "
            "a record definition."
        )

    parts = first_line.split()

    if len(parts) < 2:
        raise forms.ValidationError(
            "The WFDB header record definition "
            "is incomplete."
        )

    try:
        signal_count = int(
            parts[1]
        )
    except ValueError as exc:
        raise forms.ValidationError(
            "The WFDB header contains "
            "an invalid signal count."
        ) from exc

    if signal_count <= 0:
        raise forms.ValidationError(
            "The WFDB header must define "
            "at least one signal."
        )


def validate_ecg_file_content(
    uploaded_file,
    kind,
    extension,
):
    prefix = read_upload_prefix(
        uploaded_file
    )

    if not prefix:
        raise forms.ValidationError(
            "The uploaded ECG file is empty."
        )

    reject_dangerous_signature(
        prefix
    )

    if kind == ECGFile.FileKind.REPORT_PDF:
        validate_pdf_content(
            prefix
        )

    elif kind == ECGFile.FileKind.IMAGE:
        validate_image_content(
            prefix,
            extension,
        )

    elif kind == ECGFile.FileKind.XML:
        validate_xml_content(
            prefix
        )

    elif kind == ECGFile.FileKind.CSV:
        validate_csv_content(
            prefix
        )

    elif kind == ECGFile.FileKind.DICOM:
        validate_dicom_content(
            prefix
        )

    elif (
        kind == ECGFile.FileKind.RAW_SIGNAL
        and extension == ".edf"
    ):
        validate_edf_content(
            prefix
        )

    elif (
        kind == ECGFile.FileKind.WFDB
        and extension == ".hea"
    ):
        validate_wfdb_header_content(
            prefix
        )


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
        super().__init__(
            *args,
            **kwargs,
        )

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

        for (
            field_name,
            queryset,
        ) in scoped_querysets.items():
            if queryset is None:
                self.fields[
                    field_name
                ].queryset = (
                    self.fields[
                        field_name
                    ]
                    .queryset
                    .none()
                )
            else:
                self.fields[
                    field_name
                ].queryset = queryset

        self.fields[
            "appointment"
        ].required = False

        self.fields[
            "hospital"
        ].required = False

        self.fields[
            "branch"
        ].required = False

        self.fields[
            "department"
        ].required = False


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

    def __init__(
        self,
        *args,
        **kwargs,
    ):
        super().__init__(
            *args,
            **kwargs,
        )

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

        max_upload_mb = (
            max_upload_bytes
            // (1024 * 1024)
        )

        self.fields["file"].help_text = (
            f"Maximum file size: "
            f"{max_upload_mb} MB."
        )

    def clean_file(self):
        uploaded_file = (
            self.cleaned_data.get(
                "file"
            )
        )

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

        if (
            uploaded_file.size
            > max_upload_bytes
        ):
            max_upload_mb = (
                max_upload_bytes
                // (1024 * 1024)
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
                "The uploaded file must have "
                "a valid name."
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

        uploaded_file = cleaned_data.get(
            "file"
        )
        kind = cleaned_data.get(
            "kind"
        )

        if (
            uploaded_file is None
            or not kind
        ):
            return cleaned_data

        extension = os.path.splitext(
            os.path.basename(
                uploaded_file.name
            )
        )[1].lower()

        allowed_extensions = (
            ECG_ALLOWED_EXTENSIONS.get(
                kind,
                set(),
            )
        )

        if extension not in allowed_extensions:
            allowed_text = ", ".join(
                sorted(
                    allowed_extensions
                )
            )

            self.add_error(
                "file",
                (
                    "This file type does not match "
                    "the selected ECG file kind. "
                    f"Allowed: {allowed_text}."
                ),
            )

            return cleaned_data

        try:
            validate_ecg_file_content(
                uploaded_file,
                kind,
                extension,
            )
        except forms.ValidationError as exc:
            self.add_error(
                "file",
                exc,
            )

        return cleaned_data