import os
import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from appointments.models import Appointment
from core.private_storage import private_clinical_storage
from doctor.models import Doctor
from hospital.models import Branch, Department, Hospital
from patient.models import Patient


def ecg_file_upload_to(instance, filename):
    extension = os.path.splitext(filename)[1].lower()

    if len(extension) > 10:
        extension = ""

    record_id = instance.record_id or "unassigned"

    return (
        f"ecg/{record_id}/"
        f"{uuid.uuid4().hex}{extension}"
    )


class ECGRecord(models.Model):
    class WorkflowStatus(models.TextChoices):
        UPLOADED = "uploaded", _("Uploaded")
        READY = "ready", _("Ready for analysis")
        ANALYZING = "analyzing", _("Analyzing")
        ANALYZED = "analyzed", _("Analyzed")
        REVIEWED = "reviewed", _("Reviewed by physician")
        FAILED = "failed", _("Processing failed")

    patient = models.ForeignKey(
        Patient,
        on_delete=models.PROTECT,
        related_name="ecg_records",
    )

    doctor = models.ForeignKey(
        Doctor,
        on_delete=models.PROTECT,
        related_name="ecg_records",
    )

    appointment = models.ForeignKey(
        Appointment,
        on_delete=models.SET_NULL,
        related_name="ecg_records",
        null=True,
        blank=True,
    )

    hospital = models.ForeignKey(
        Hospital,
        on_delete=models.PROTECT,
        related_name="ecg_records",
        null=True,
        blank=True,
    )

    branch = models.ForeignKey(
        Branch,
        on_delete=models.PROTECT,
        related_name="ecg_records",
        null=True,
        blank=True,
    )

    department = models.ForeignKey(
        Department,
        on_delete=models.PROTECT,
        related_name="ecg_records",
        null=True,
        blank=True,
    )

    recorded_at = models.DateTimeField(
        default=timezone.now,
        db_index=True,
    )

    device_manufacturer = models.CharField(
        max_length=120,
        blank=True,
    )

    device_model = models.CharField(
        max_length=120,
        blank=True,
    )

    sampling_frequency_hz = models.PositiveIntegerField(
        null=True,
        blank=True,
    )

    lead_count = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
    )

    duration_seconds = models.DecimalField(
        max_digits=8,
        decimal_places=2,
        null=True,
        blank=True,
    )

    workflow_status = models.CharField(
        max_length=20,
        choices=WorkflowStatus.choices,
        default=WorkflowStatus.UPLOADED,
        db_index=True,
    )

    notes = models.TextField(
        blank=True,
    )

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="created_ecg_records",
        null=True,
        blank=True,
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
        db_index=True,
    )

    updated_at = models.DateTimeField(
        auto_now=True,
    )

    class Meta:
        ordering = ["-recorded_at", "-pk"]
        indexes = [
            models.Index(
                fields=["patient", "recorded_at"],
                name="ecg_patient_recorded_idx",
            ),
            models.Index(
                fields=["doctor", "recorded_at"],
                name="ecg_doctor_recorded_idx",
            ),
        ]

    def clean(self):
        super().clean()

        errors = {}

        if self.appointment_id:
            appointment = self.appointment

            if self.patient_id != appointment.patient_id:
                errors["patient"] = _(
                    "The ECG patient must match the appointment patient."
                )

            if self.doctor_id != appointment.doctor_id:
                errors["doctor"] = _(
                    "The ECG doctor must match the appointment doctor."
                )

            location_fields = (
                "hospital",
                "branch",
                "department",
            )

            for field_name in location_fields:
                record_value = getattr(
                    self,
                    f"{field_name}_id",
                )
                appointment_value = getattr(
                    appointment,
                    f"{field_name}_id",
                )

                if (
                    record_value is not None
                    and record_value != appointment_value
                ):
                    errors[field_name] = _(
                        "The ECG location must match the appointment location."
                    )

        if (
            self.branch_id
            and self.hospital_id
            and self.branch.hospital_id != self.hospital_id
        ):
            errors["branch"] = _(
                "The selected branch does not belong to the selected hospital."
            )

        if self.department_id:
            if not self.branch_id:
                errors["branch"] = _(
                    "A branch is required when a department is selected."
                )
            elif self.department.branch_id != self.branch_id:
                errors["department"] = _(
                    "The selected department does not belong to the selected branch."
                )

        if errors:
            raise ValidationError(errors)

    def __str__(self):
        return f"ECGRecord #{self.pk or 'new'}"


class ECGFile(models.Model):
    class FileKind(models.TextChoices):
        RAW_SIGNAL = "raw_signal", _("Raw ECG signal")
        REPORT_PDF = "report_pdf", _("ECG report PDF")
        IMAGE = "image", _("ECG image")
        XML = "xml", _("XML")
        DICOM = "dicom", _("DICOM")
        WFDB = "wfdb", _("WFDB")
        CSV = "csv", _("CSV")
        OTHER = "other", _("Other")

    record = models.ForeignKey(
        ECGRecord,
        on_delete=models.CASCADE,
        related_name="files",
    )

    source_archive_attachment = models.OneToOneField(
        "medical_archive.ArchiveAttachment",
        on_delete=models.SET_NULL,
        related_name="imported_ecg_file",
        null=True,
        blank=True,
    )

    file = models.FileField(
        storage=private_clinical_storage,
        upload_to=ecg_file_upload_to,
    )

    kind = models.CharField(
        max_length=20,
        choices=FileKind.choices,
        default=FileKind.RAW_SIGNAL,
        db_index=True,
    )

    mime_type = models.CharField(
        max_length=120,
        blank=True,
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    class Meta:
        ordering = ["pk"]

    def __str__(self):
        return f"ECGFile #{self.pk or 'new'}"