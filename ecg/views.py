import mimetypes
import os

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import transaction
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from medical_archive.access import filter_archives_for_user
from medical_archive.models import ArchiveAttachment, PatientArchive

from .access import (
    active_location_assignments,
    assigned_doctor_for,
    ecg_form_querysets_for_user,
    filter_ecg_records_for_user,
)
from .forms import ECGFileForm, ECGRecordForm
from .models import ECGFile, ECGRecord
from .services.parser import (
    ECGParseError,
    parse_csv_ecg,
)
from .services.waveform import (
    ECGWaveformError,
    build_waveform_preview,
)


def _archive_attachment_ecg_kind(attachment):
    """
    Map a supported medical-archive attachment to the
    corresponding ECG file kind.

    The medical archive currently accepts image/PDF handoff
    files, while the ECG module performs its own stricter
    validation before importing the file.
    """
    if not attachment or not attachment.file:
        return None

    extension = os.path.splitext(
        attachment.file.name or ""
    )[1].lower()

    if extension == ".pdf":
        return ECGFile.FileKind.REPORT_PDF

    if extension in {
        ".jpg",
        ".jpeg",
        ".png",
    }:
        return ECGFile.FileKind.IMAGE

    return None


def _ecg_import_location(user, archive):
    """
    Resolve a location for an ECG record imported from
    the medical archive.

    Appointment location takes precedence. When there is
    no appointment, use the doctor's primary active staff
    assignment so the imported ECG remains inside the same
    access scope as the doctor.
    """
    if archive.appointment_id:
        appointment = archive.appointment

        return {
            "hospital": appointment.hospital,
            "branch": appointment.branch,
            "department": appointment.department,
        }

    assignment = (
        active_location_assignments(user)
        .first()
    )

    if assignment is None:
        return {
            "hospital": None,
            "branch": None,
            "department": None,
        }

    return {
        "hospital": assignment.hospital,
        "branch": assignment.branch,
        "department": assignment.department,
    }


def _read_archive_attachment(attachment):
    """
    Read an archive attachment into an uploaded-file object
    so it can pass through ECGFileForm and all ECG-specific
    file validation before being copied into ECG storage.
    """
    if not attachment.file:
        raise FileNotFoundError

    source_name = os.path.basename(
        attachment.file.name or ""
    )

    if not source_name:
        source_name = (
            f"archive-attachment-{attachment.pk}"
        )

    try:
        attachment.file.open("rb")
        content = attachment.file.read()
    finally:
        try:
            attachment.file.close()
        except Exception:
            pass

    content_type = (
        getattr(
            attachment,
            "mime_type",
            "",
        )
        or mimetypes.guess_type(
            source_name
        )[0]
        or "application/octet-stream"
    )

    return SimpleUploadedFile(
        source_name,
        content,
        content_type=content_type,
    )


@login_required
def dashboard(request):
    if not request.user.has_perm("ecg.view_ecgrecord"):
        raise PermissionDenied

    records = filter_ecg_records_for_user(
        ECGRecord.objects.select_related(
            "patient",
            "doctor",
            "doctor__user",
            "appointment",
            "hospital",
            "branch",
            "department",
        ),
        request.user,
    )[:10]

    return render(
        request,
        "ecg/dashboard.html",
        {
            "records": records,
            "can_add_record": request.user.has_perm(
                "ecg.add_ecgrecord"
            ),
        },
    )


@login_required
def create_record(request):
    if not request.user.has_perm("ecg.add_ecgrecord"):
        raise PermissionDenied

    form = ECGRecordForm(
        request.POST or None,
        **ecg_form_querysets_for_user(request.user),
    )

    if request.method == "POST" and form.is_valid():
        record = form.save(commit=False)
        record.created_by = request.user
        record.save()

        messages.success(
            request,
            "ECG record created successfully.",
        )

        return redirect(
            "ecg:record_detail",
            record_id=record.pk,
        )

    return render(
        request,
        "ecg/create_record.html",
        {
            "form": form,
        },
    )


@login_required
@require_POST
def analyze_archive_ecg(
    request,
    archive_id,
):
    """
    Import an ECG handoff from the medical archive into the
    ECG workspace.

    The operation is doctor-only, permission-protected,
    scope-protected and idempotent. The source archive file
    remains untouched; a validated copy is stored in the ECG
    private storage.

    Repeating the request for the same ArchiveAttachment
    returns the already-created ECG record instead of
    creating duplicates.
    """
    if getattr(
        request.user,
        "role",
        "",
    ) != "doctor":
        raise PermissionDenied

    required_permissions = (
        "medical_archive.view_patientarchive",
        "medical_archive.view_archiveattachment",
        "ecg.view_ecgrecord",
        "ecg.add_ecgrecord",
        "ecg.view_ecgfile",
        "ecg.add_ecgfile",
    )

    if not all(
        request.user.has_perm(permission)
        for permission in required_permissions
    ):
        raise PermissionDenied

    doctor = assigned_doctor_for(
        request.user
    )

    if doctor is None:
        raise PermissionDenied

    archive_queryset = (
        filter_archives_for_user(
            PatientArchive.objects.select_related(
                "patient",
                "doctor",
                "doctor__user",
                "appointment",
                "appointment__hospital",
                "appointment__branch",
                "appointment__department",
            ),
            request.user,
        )
    )

    archive = get_object_or_404(
        archive_queryset,
        pk=archive_id,
        title="ECG Recording",
    )

    if (
        not archive.patient_id
        or not archive.doctor_id
        or archive.doctor_id != doctor.pk
    ):
        raise PermissionDenied

    attachments = (
        ArchiveAttachment.objects
        .filter(
            archive=archive,
        )
        .order_by(
            "pk",
        )
    )

    attachment = None
    file_kind = None

    for candidate in attachments:
        candidate_kind = (
            _archive_attachment_ecg_kind(
                candidate
            )
        )

        if candidate_kind is not None:
            attachment = candidate
            file_kind = candidate_kind
            break

    if attachment is None:
        messages.error(
            request,
            (
                "No supported ECG attachment was found. "
                "The current archive-to-ECG bridge supports "
                "PDF, JPG, JPEG and PNG files."
            ),
        )

        return redirect(
            "medical_archive:archive_detail",
            archive_id=archive.pk,
        )

    existing_file = (
        ECGFile.objects
        .select_related(
            "record",
        )
        .filter(
            source_archive_attachment=attachment,
        )
        .first()
    )

    if existing_file is not None:
        messages.info(
            request,
            (
                "This ECG file is already available "
                "in the ECG workspace."
            ),
        )

        return redirect(
            "ecg:record_detail",
            record_id=existing_file.record_id,
        )

    try:
        uploaded_file = (
            _read_archive_attachment(
                attachment
            )
        )
    except (
        FileNotFoundError,
        OSError,
        ValueError,
    ):
        messages.error(
            request,
            (
                "The ECG attachment could not be read "
                "from the medical archive."
            ),
        )

        return redirect(
            "medical_archive:archive_detail",
            archive_id=archive.pk,
        )

    file_form = ECGFileForm(
        data={
            "kind": file_kind,
        },
        files={
            "file": uploaded_file,
        },
    )

    if not file_form.is_valid():
        messages.error(
            request,
            (
                "The archive file did not pass the ECG "
                "file validation checks."
            ),
        )

        return redirect(
            "medical_archive:archive_detail",
            archive_id=archive.pk,
        )

    location = _ecg_import_location(
        request.user,
        archive,
    )

    try:
        with transaction.atomic():
            locked_attachment = (
                ArchiveAttachment.objects
                .select_for_update()
                .get(
                    pk=attachment.pk,
                    archive=archive,
                )
            )

            existing_file = (
                ECGFile.objects
                .select_related(
                    "record",
                )
                .filter(
                    source_archive_attachment=(
                        locked_attachment
                    ),
                )
                .first()
            )

            if existing_file is not None:
                record = existing_file.record

            else:
                record = ECGRecord(
                    patient=archive.patient,
                    doctor=archive.doctor,
                    appointment=archive.appointment,
                    hospital=location["hospital"],
                    branch=location["branch"],
                    department=location[
                        "department"
                    ],
                    recorded_at=archive.created_at,
                    workflow_status=(
                        ECGRecord.WorkflowStatus.UPLOADED
                    ),
                    notes=archive.notes or "",
                    created_by=request.user,
                )

                record.full_clean()
                record.save()

                uploaded_file.seek(0)

                ecg_file = file_form.save(
                    commit=False
                )

                ecg_file.record = record
                ecg_file.source_archive_attachment = (
                    locked_attachment
                )

                ecg_file.save()

    except (
        ArchiveAttachment.DoesNotExist,
        ValidationError,
    ):
        messages.error(
            request,
            (
                "The ECG record could not be imported "
                "from the medical archive."
            ),
        )

        return redirect(
            "medical_archive:archive_detail",
            archive_id=archive.pk,
        )

    messages.success(
        request,
        (
            "ECG file transferred to the ECG "
            "workspace successfully."
        ),
    )

    return redirect(
        "ecg:record_detail",
        record_id=record.pk,
    )


@login_required
def record_detail(request, record_id):
    if not request.user.has_perm("ecg.view_ecgrecord"):
        raise PermissionDenied

    queryset = filter_ecg_records_for_user(
        ECGRecord.objects.select_related(
            "patient",
            "doctor",
            "doctor__user",
            "appointment",
            "hospital",
            "branch",
            "department",
            "created_by",
        ).prefetch_related(
            "files",
        ),
        request.user,
    )

    record = get_object_or_404(
        queryset,
        pk=record_id,
    )

    can_download_file = request.user.has_perm(
        "ecg.view_ecgfile"
    )

    waveform_preview = None
    waveform_file = None
    waveform_error = False
    waveform_chart_data = None

    if can_download_file:
        waveform_file = next(
            (
                ecg_file
                for ecg_file in record.files.all()
                if ecg_file.kind
                == ECGFile.FileKind.CSV
            ),
            None,
        )

        if waveform_file is not None:
            try:
                parsed_ecg = parse_csv_ecg(
                    waveform_file
                )

                waveform_preview = (
                    build_waveform_preview(
                        parsed_ecg
                    )
                )

                waveform_chart_data = {
                    "x_values": list(
                        waveform_preview.x_values
                    ),
                    "x_unit": (
                        waveform_preview.x_unit
                    ),
                    "leads": [
                        {
                            "name": lead.name,
                            "values": list(
                                lead.values
                            ),
                        }
                        for lead in waveform_preview.leads
                    ],
                    "source_sample_count": (
                        waveform_preview.source_sample_count
                    ),
                    "displayed_sample_count": (
                        waveform_preview.displayed_sample_count
                    ),
                    "downsampled": (
                        waveform_preview.downsampled
                    ),
                }

            except (
                ECGParseError,
                ECGWaveformError,
            ):
                waveform_preview = None
                waveform_chart_data = None
                waveform_error = True

    return render(
        request,
        "ecg/record_detail.html",
        {
            "record": record,
            "can_upload_file": (
                request.user.has_perm(
                    "ecg.add_ecgfile"
                )
            ),
            "can_download_file": (
                can_download_file
            ),
            "waveform_preview": (
                waveform_preview
            ),
            "waveform_file": waveform_file,
            "waveform_error": waveform_error,
            "waveform_chart_data": (
                waveform_chart_data
            ),
        },
    )


@login_required
def upload_file(request, record_id):
    if not request.user.has_perm(
        "ecg.view_ecgrecord"
    ):
        raise PermissionDenied

    if not request.user.has_perm(
        "ecg.add_ecgfile"
    ):
        raise PermissionDenied

    queryset = filter_ecg_records_for_user(
        ECGRecord.objects.select_related(
            "patient",
            "doctor",
            "appointment",
            "hospital",
            "branch",
            "department",
        ),
        request.user,
    )

    record = get_object_or_404(
        queryset,
        pk=record_id,
    )

    form = ECGFileForm(
        request.POST or None,
        request.FILES or None,
    )

    if request.method == "POST" and form.is_valid():
        ecg_file = form.save(
            commit=False
        )

        ecg_file.record = record
        ecg_file.save()

        messages.success(
            request,
            "ECG file uploaded successfully.",
        )

        return redirect(
            "ecg:record_detail",
            record_id=record.pk,
        )

    return render(
        request,
        "ecg/upload_file.html",
        {
            "form": form,
            "record": record,
        },
    )


@login_required
def download_file(
    request,
    record_id,
    file_id,
):
    if not request.user.has_perm(
        "ecg.view_ecgrecord"
    ):
        raise PermissionDenied

    if not request.user.has_perm(
        "ecg.view_ecgfile"
    ):
        raise PermissionDenied

    record_queryset = filter_ecg_records_for_user(
        ECGRecord.objects.all(),
        request.user,
    )

    record = get_object_or_404(
        record_queryset,
        pk=record_id,
    )

    ecg_file = get_object_or_404(
        ECGFile.objects.select_related(
            "record",
        ),
        pk=file_id,
        record=record,
    )

    extension = os.path.splitext(
        os.path.basename(
            ecg_file.file.name
        )
    )[1].lower()

    if len(extension) > 10:
        extension = ""

    download_name = (
        f"ecg-record-{record.pk}"
        f"-file-{ecg_file.pk}"
        f"{extension}"
    )

    try:
        file_handle = ecg_file.file.open("rb")
    except (FileNotFoundError, ValueError):
        raise Http404(
            "ECG file not found."
        )

    response = FileResponse(
        file_handle,
        as_attachment=True,
        filename=download_name,
        content_type="application/octet-stream",
    )

    response["Cache-Control"] = (
        "private, no-store"
    )
    response["Pragma"] = "no-cache"
    response["X-Content-Type-Options"] = (
        "nosniff"
    )

    return response
