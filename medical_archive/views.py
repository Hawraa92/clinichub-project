# File: medical_archive/views.py
from __future__ import annotations

import io
import logging
import os
import re
from datetime import date
from typing import Any, Dict, List, Optional, Tuple
from xml.sax.saxutils import escape as xml_escape

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Q, QuerySet
from django.http import FileResponse, Http404, HttpRequest, HttpResponse, JsonResponse, QueryDict
from django.shortcuts import get_object_or_404, redirect, render
from django.template.defaultfilters import filesizeformat
from django.urls import reverse
from django.utils.dateparse import parse_date
from django.utils.html import strip_tags
from django.views.decorators.http import require_http_methods

from doctor.models import Doctor
from patient.models import Patient
from .forms import ArchiveAttachmentForm, ArchiveVoiceNoteForm, PatientArchiveForm
from .models import ArchiveAttachment, ArchiveVoiceNote, PatientArchive
from .access import (
    can_edit_archive as _access_can_edit_archive,
    filter_archives_for_user,
    filter_doctors_for_user,
    filter_patients_for_user,
    is_authorized_for_archive as _access_is_authorized_for_archive,
)

# =========================
# PDF (ReportLab)
# =========================
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT, TA_RIGHT
from reportlab.lib.fonts import addMapping
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

logger = logging.getLogger(__name__)

# Optional Arabic shaping (best-effort)
try:
    import arabic_reshaper  # type: ignore
    from bidi.algorithm import get_display  # type: ignore

    _HAS_AR_SHAPING = True
except Exception:
    _HAS_AR_SHAPING = False


# =========================
# RBAC
# =========================
ROLE_PRIVILEGED = {"admin", "secretary"}
ROLE_CREATE_ALLOWED = {"admin", "secretary", "doctor"}  # superuser allowed always

PERM_VIEW_ARCHIVE = "medical_archive.view_patientarchive"
PERM_ADD_ARCHIVE = "medical_archive.add_patientarchive"
PERM_CHANGE_ARCHIVE = "medical_archive.change_patientarchive"
PERM_DELETE_ARCHIVE = "medical_archive.delete_patientarchive"

PERM_VIEW_ATTACHMENT = "medical_archive.view_archiveattachment"
PERM_ADD_ATTACHMENT = "medical_archive.add_archiveattachment"

PERM_VIEW_VOICE_NOTE = "medical_archive.view_archivevoicenote"
PERM_ADD_VOICE_NOTE = "medical_archive.add_archivevoicenote"

_AR_RE = re.compile(r"[\u0600-\u06FF\u0750-\u077F\u08A0-\u08FF]")

# IMPORTANT:
# FILES keys are the "name" attribute (NOT id). Keeping some id_* keys is harmless
# because your earlier codebase sometimes used non-standard names.
VOICE_FILE_KEYS = {
    "audio",
    "id_audio",
    "voice_audio",
    "id_voice_audio",
}


def _get_role(user) -> Optional[str]:
    return getattr(user, "role", None)


def _is_ajax(request: HttpRequest) -> bool:
    """
    Detect AJAX safely.
    - x-requested-with: XMLHttpRequest
    - Accept includes application/json
    - htmx (optional): HX-Request
    """
    xr = request.headers.get("x-requested-with") == "XMLHttpRequest"
    accept_json = "application/json" in (request.headers.get("accept") or "")
    hx = request.headers.get("HX-Request") == "true"
    return bool(xr or accept_json or hx)


def _model_has_field(model, field_name: str) -> bool:
    try:
        model._meta.get_field(field_name)
        return True
    except Exception:
        return False


def _is_authorized_for_archive(user, archive: PatientArchive) -> bool:
    return _access_is_authorized_for_archive(
        user,
        archive,
    )

def _can_edit_archive(user, archive: PatientArchive) -> bool:
    return _access_can_edit_archive(
        user,
        archive,
    )

def _parse_date_range(start_str: str, end_str: str) -> Tuple[Optional[date], Optional[date]]:
    start = parse_date(start_str) if start_str else None
    end = parse_date(end_str) if end_str else None
    return start, end


def _get_doctors_patients_for_user(user) -> Tuple[QuerySet, QuerySet]:
    doctors = filter_doctors_for_user(
        Doctor.objects.select_related("user").all(),
        user,
    )
    patients = filter_patients_for_user(
        Patient.objects.all().order_by("full_name"),
        user,
    )
    return doctors, patients

def _json_error(message: str, status: int = 400, extra: Optional[dict] = None) -> JsonResponse:
    payload: Dict[str, Any] = {"ok": False, "message": message}
    if extra:
        payload.update(extra)
    return JsonResponse(payload, status=status)


def _json_success(message: str, redirect_url: Optional[str] = None, extra: Optional[dict] = None) -> JsonResponse:
    payload: Dict[str, Any] = {"ok": True, "message": message}
    if redirect_url:
        payload["redirect"] = redirect_url
    if extra:
        payload.update(extra)
    return JsonResponse(payload)


def _form_errors_json(form) -> Dict[str, Any]:
    """
    Ensure form errors are JSON-serializable.
    """
    try:
        return form.errors.get_json_data()
    except Exception:
        out: Dict[str, Any] = {}
        for k, v in getattr(form, "errors", {}).items():
            out[k] = [str(x) for x in v]
        return out


def _add_form_errors_as_messages(request: HttpRequest, form, prefix: str) -> None:
    """
    Add form errors to Django messages without duplicates.
    """
    seen = set()

    for field, errs in form.errors.items():
        for err in errs:
            msg = f"{prefix} {field}: {err}" if field != "__all__" else f"{prefix} {err}"
            if msg not in seen:
                messages.error(request, msg)
                seen.add(msg)

    for err in form.non_field_errors():
        msg = f"{prefix} {err}"
        if msg not in seen:
            messages.error(request, msg)
            seen.add(msg)


def _fix_title_collision(post: QueryDict) -> Tuple[QueryDict, QueryDict]:
    """
    IMPORTANT:
    Your page contains TWO fields named "title":
      - archive_form.title (Record Title)
      - voice_form.title (Voice Title)
    This causes collisions in request.POST.

    Fix without changing HTML:
    - archive_title = first "title" value
    - voice_title   = last  "title" value (can be empty)

    Returns: (archive_data, voice_data)
    """
    archive_data = post.copy()
    voice_data = post.copy()

    titles = [t for t in post.getlist("title") if t is not None]
    if len(titles) >= 2:
        archive_data["title"] = titles[0]
        voice_data["title"] = titles[-1]

    return archive_data, voice_data


def _extract_attachment_files(request: HttpRequest) -> List:
    """
    Robustly extract attachment files even if the input name changes.
    - Tries common keys first
    - Falls back to "any FILES key" except voice keys
    """
    for key in ("files", "id_files", "files[]", "attachments", "attachment_files"):
        files = request.FILES.getlist(key)
        if files:
            return [f for f in files if f]

    out: List = []
    for key, file_list in request.FILES.lists():
        if key in VOICE_FILE_KEYS:
            continue
        out.extend([f for f in file_list if f])
    return out


def _patch_files_for_attachment_form(request: HttpRequest, extracted_files: List):
    """
    Ensure ArchiveAttachmentForm sees files under the expected field name "files".
    """
    files_copy = request.FILES.copy()
    try:
        current = files_copy.getlist("files")
    except Exception:
        current = []

    if extracted_files and not current:
        try:
            files_copy.setlist("files", extracted_files)
        except Exception:
            pass

    return files_copy


def _extract_voice_file(request: HttpRequest):
    """
    Return the first voice file found under any known voice key.
    """
    for k in VOICE_FILE_KEYS:
        try:
            f = request.FILES.get(k)
        except Exception:
            f = None
        if f:
            return f

    for k in VOICE_FILE_KEYS:
        try:
            lst = request.FILES.getlist(k)
        except Exception:
            lst = []
        if lst:
            return lst[0]

    return None


def _patch_files_for_voice_form(request: HttpRequest):
    """
    Ensure ArchiveVoiceNoteForm sees the voice file under expected name "audio".
    """
    files_copy = request.FILES.copy()
    voice_file = _extract_voice_file(request)

    if voice_file:
        if not files_copy.get("audio"):
            try:
                files_copy.setlist("audio", [voice_file])
            except Exception:
                try:
                    files_copy["audio"] = voice_file
                except Exception:
                    pass

    return files_copy


def _voice_file_present(request: HttpRequest) -> bool:
    return bool(_extract_voice_file(request))


def _shorten_middle(text: str, max_len: int = 42) -> str:
    text = text or ""
    if len(text) <= max_len:
        return text
    head = max(10, (max_len // 2) - 2)
    tail = max(8, (max_len // 2) - 2)
    return f"{text[:head]}…{text[-tail:]}"


# =========================
# PDF helpers (fonts + Arabic)
# =========================
_PDF_FONT_LATIN = "ClinicHubPDFLatin"
_PDF_FONT_AR = "ClinicHubPDFArabic"
_PDF_FONTS_REGISTERED = False


def _ensure_font_mapping(font_name: str) -> None:
    addMapping(font_name, 0, 0, font_name)
    addMapping(font_name, 1, 0, font_name)
    addMapping(font_name, 0, 1, font_name)
    addMapping(font_name, 1, 1, font_name)


def _existing_paths(paths: List[str]) -> List[str]:
    seen = set()
    out: List[str] = []
    for p in paths:
        if not p:
            continue
        if p in seen:
            continue
        seen.add(p)
        if os.path.exists(p):
            out.append(p)
    return out


def _try_latin_font_paths() -> List[str]:
    """
    Prefer fonts that cover BOTH Latin + Arabic if possible (DejaVuSans, Arial).
    Put your own fonts in: static/fonts/
    """
    base = getattr(settings, "BASE_DIR", None) or os.getcwd()

    candidates = [
        os.path.join(base, "static", "fonts", "DejaVuSans.ttf"),
        os.path.join(base, "static", "fonts", "Arial.ttf"),
        os.path.join(base, "static", "fonts", "arial.ttf"),
    ]

    # Linux common
    candidates += [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    ]

    # Windows common
    if os.name == "nt":
        win = os.environ.get("WINDIR", r"C:\Windows")
        fonts = os.path.join(win, "Fonts")
        candidates += [
            os.path.join(fonts, "arial.ttf"),
            os.path.join(fonts, "ARIAL.TTF"),
            os.path.join(fonts, "tahoma.ttf"),
            os.path.join(fonts, "TAHOMA.TTF"),
            os.path.join(fonts, "segoeui.ttf"),
            os.path.join(fonts, "SEGOEUI.TTF"),
        ]

    return _existing_paths(candidates)


def _try_arabic_font_paths() -> List[str]:
    """
    Arabic-optimized fonts (best appearance).
    Put one of these in static/fonts/ for perfect Arabic:
    - NotoNaskhArabic-Regular.ttf
    - Amiri-Regular.ttf
    """
    base = getattr(settings, "BASE_DIR", None) or os.getcwd()

    candidates = [
        os.path.join(base, "static", "fonts", "NotoNaskhArabic-Regular.ttf"),
        os.path.join(base, "static", "fonts", "Amiri-Regular.ttf"),
        os.path.join(base, "static", "fonts", "NotoSansArabic-Regular.ttf"),
        # fallback: DejaVu can still render Arabic
        os.path.join(base, "static", "fonts", "DejaVuSans.ttf"),
    ]

    # Linux common (Render etc.)
    candidates += [
        "/usr/share/fonts/truetype/noto/NotoNaskhArabic-Regular.ttf",
        "/usr/share/fonts/truetype/noto/NotoSansArabic-Regular.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]

    # Windows common (not perfect Arabic, but works)
    if os.name == "nt":
        win = os.environ.get("WINDIR", r"C:\Windows")
        fonts = os.path.join(win, "Fonts")
        candidates += [
            os.path.join(fonts, "arial.ttf"),
            os.path.join(fonts, "ARIAL.TTF"),
            os.path.join(fonts, "tahoma.ttf"),
            os.path.join(fonts, "TAHOMA.TTF"),
        ]

    return _existing_paths(candidates)


def _font_is_registered(name: str) -> bool:
    try:
        pdfmetrics.getFont(name)
        return True
    except Exception:
        return False


def _register_pdf_fonts() -> Tuple[str, str]:
    """
    Returns: (latin_font_name, arabic_font_name)

    Fixes Arabic "black squares" issue:
    - happens when ReportLab falls back to Helvetica (no Arabic glyphs).
    - This function tries OS + project fonts and embeds a TTF.
    """
    global _PDF_FONTS_REGISTERED

    if _PDF_FONTS_REGISTERED:
        latin = _PDF_FONT_LATIN if _font_is_registered(_PDF_FONT_LATIN) else "Helvetica"
        ar = _PDF_FONT_AR if _font_is_registered(_PDF_FONT_AR) else latin
        return latin, ar

    latin_paths = _try_latin_font_paths()
    ar_paths = _try_arabic_font_paths()

    latin_font = "Helvetica"
    ar_font = "Helvetica"

    if latin_paths:
        try:
            pdfmetrics.registerFont(TTFont(_PDF_FONT_LATIN, latin_paths[0]))
            _ensure_font_mapping(_PDF_FONT_LATIN)
            latin_font = _PDF_FONT_LATIN
        except Exception as e:
            logger.debug("PDF latin font register failed: %s", e)

    if ar_paths:
        try:
            pdfmetrics.registerFont(TTFont(_PDF_FONT_AR, ar_paths[0]))
            _ensure_font_mapping(_PDF_FONT_AR)
            ar_font = _PDF_FONT_AR
        except Exception as e:
            logger.debug("PDF arabic font register failed: %s", e)

    # If Arabic failed but Latin is a TTF, use Latin for Arabic too (still better than Helvetica)
    if ar_font == "Helvetica" and latin_font != "Helvetica":
        ar_font = latin_font

    _PDF_FONTS_REGISTERED = True
    return latin_font, ar_font


def _has_arabic(text: str) -> bool:
    return bool(text and _AR_RE.search(text))


def _shape_text_for_pdf(text: str) -> str:
    if not text:
        return ""
    t = text.replace("\u00A0", " ")
    if _HAS_AR_SHAPING and _has_arabic(t):
        try:
            reshaped = arabic_reshaper.reshape(t)
            return get_display(reshaped)
        except Exception:
            return t
    return t


def _fmt_dt(dt) -> str:
    try:
        return dt.strftime("%Y-%m-%d %I:%M %p")
    except Exception:
        return "—"


def _p_text(text: str) -> str:
    return xml_escape(text or "").replace("\n", "<br/>")


# =========================
# List / Filter
# =========================
@login_required
@permission_required(PERM_VIEW_ARCHIVE, raise_exception=True)
def archive_list(request: HttpRequest) -> HttpResponse:
    user = request.user
    role = _get_role(user)

    base_qs = (
        PatientArchive.objects.select_related(
            "patient",
            "patient__user",
            "doctor",
            "doctor__user",
        )
        .order_by("-created_at")
    )

    archives = filter_archives_for_user(
        base_qs,
        user,
    )

    selected_type = (request.GET.get("type", "") or "").strip()
    selected_doctor = (request.GET.get("doctor", "") or "").strip()
    search = (request.GET.get("search", "") or "").strip()
    start_str = (request.GET.get("start_date", "") or "").strip()
    end_str = (request.GET.get("end_date", "") or "").strip()

    if selected_type:
        archives = archives.filter(archive_type=selected_type)

    if selected_doctor:
        if selected_doctor.isdigit():
            archives = archives.filter(doctor_id=int(selected_doctor))
        else:
            messages.warning(request, "⚠️ Invalid doctor filter.")

    if search:
        archives = archives.filter(
            Q(patient__full_name__icontains=search)
            | Q(title__icontains=search)
            | Q(notes__icontains=search)
        )

    start_date, end_date = _parse_date_range(start_str, end_str)
    if start_str and start_date is None:
        messages.warning(request, "⚠️ Invalid start date format. Use YYYY-MM-DD.")
    if end_str and end_date is None:
        messages.warning(request, "⚠️ Invalid end date format. Use YYYY-MM-DD.")

    if start_date:
        archives = archives.filter(created_at__date__gte=start_date)
    if end_date:
        archives = archives.filter(created_at__date__lte=end_date)

    paginator = Paginator(archives, 10)
    page_number = request.GET.get("page")
    page_obj = paginator.get_page(page_number)

    types = getattr(PatientArchive, "ARCHIVE_TYPES", [])
    doctors, patients = _get_doctors_patients_for_user(user)

    return render(
        request,
        "medical_archive/archive_list.html",
        {
            "page_obj": page_obj,
            "types": types,
            "doctors": doctors,
            "patients": patients,
            "selected_type": selected_type,
            "selected_doctor": selected_doctor,
            "search": search,
            "start_date": start_str,
            "end_date": end_str,
        },
    )


# =========================
# Quick clinical handoff
# Secretary/Admin -> Patient -> Doctor -> Attachment
# =========================
@login_required
@permission_required(PERM_ADD_ARCHIVE, raise_exception=True)
@require_http_methods(["POST"])
def quick_send_to_doctor(request: HttpRequest) -> JsonResponse:
    """
    Create a single clinical handoff from the secretary/admin dashboard.
    Security guarantees:
    - Only admin/secretary accounts (or a superuser) can use this endpoint.
    - The caller must have add permissions for both archive and attachment.
    - Patient and doctor IDs are resolved only from the caller's scoped
      querysets, so out-of-scope objects are never accepted.
    - The attachment is validated by the existing ArchiveAttachmentForm.
    - Archive and attachment are saved in one atomic transaction.
    - No general archive view/change/delete permission is granted here.
    """
    user = request.user
    role = _get_role(user)
    if not (
        getattr(user, "is_superuser", False)
        or role in ROLE_PRIVILEGED
    ):
        raise Http404("Not found.")
    if not user.has_perm(PERM_ADD_ATTACHMENT):
        return _json_error(
            "You do not have permission to add archive attachments.",
            status=403,
        )
    patient_raw = (
        request.POST.get("patient_id")
        or request.POST.get("patient")
        or ""
    )
    doctor_raw = (
        request.POST.get("doctor_id")
        or request.POST.get("doctor")
        or ""
    )
    try:
        patient_id = int(str(patient_raw).strip())
        doctor_id = int(str(doctor_raw).strip())
    except (TypeError, ValueError, OverflowError):
        return _json_error(
            "Please select a valid patient and doctor.",
            status=400,
        )
    if patient_id <= 0 or doctor_id <= 0:
        return _json_error(
            "Please select a valid patient and doctor.",
            status=400,
        )
    scoped_patients = filter_patients_for_user(
        Patient.objects.all(),
        user,
    )
    scoped_doctors = filter_doctors_for_user(
        Doctor.objects.select_related("user").all(),
        user,
    )
    # Use 404 for out-of-scope IDs so the endpoint does not reveal whether
    # another tenant's patient or doctor exists.
    patient = get_object_or_404(scoped_patients, pk=patient_id)
    doctor = get_object_or_404(scoped_doctors, pk=doctor_id)
    clinical_type = (
        request.POST.get("clinical_type")
        or "file"
    ).strip().lower()
    type_config = {
        "photo": {
            "title": "Clinical Photo",
            "archive_type": "scan",
            "description": "Clinical photo",
        },
        "ecg": {
            "title": "ECG Recording",
            "archive_type": "scan",
            "description": "ECG recording",
        },
        "file": {
            "title": "Clinical File",
            "archive_type": "other",
            "description": "Clinical file",
        },
    }
    config = type_config.get(clinical_type)
    if config is None:
        return _json_error(
            "Invalid clinical file type.",
            status=400,
        )
    extracted_files = _extract_attachment_files(request)
    if not extracted_files:
        return _json_error(
            "Please select a file to send.",
            status=400,
        )
    if len(extracted_files) != 1:
        return _json_error(
            "Please send one file at a time.",
            status=400,
        )
    patched_files = _patch_files_for_attachment_form(
        request,
        extracted_files,
    )
    attachment_post = request.POST.copy()
    if not (attachment_post.get("description") or "").strip():
        attachment_post["description"] = config["description"]
    attachment_form = ArchiveAttachmentForm(
        attachment_post,
        patched_files,
    )
    if not attachment_form.is_valid():
        return _json_error(
            "Attachment validation failed.",
            status=400,
            extra={
                "attachment_errors": _form_errors_json(
                    attachment_form
                ),
            },
        )
    note = (
        request.POST.get("note")
        or request.POST.get("notes")
        or ""
    ).strip()
    archive_data = request.POST.copy()
    archive_data["patient"] = str(patient.pk)
    archive_data["title"] = config["title"]
    archive_data["archive_type"] = config["archive_type"]
    archive_data["notes"] = note
    archive_data["is_critical"] = ""
    # Reuse the existing form so patient scoping and archive validation stay
    # centralized in one place.
    archive_form = PatientArchiveForm(
        archive_data,
        user=user,
    )
    if not archive_form.is_valid():
        return _json_error(
            "Archive validation failed.",
            status=400,
            extra={
                "archive_errors": _form_errors_json(
                    archive_form
                ),
            },
        )
    try:
        with transaction.atomic():
            archive = archive_form.save(commit=False)
            archive.patient = patient
            archive.doctor = doctor
            if _model_has_field(PatientArchive, "status"):
                archive.status = "final"
            if (
                _model_has_field(PatientArchive, "created_by")
                and not getattr(archive, "created_by_id", None)
            ):
                archive.created_by = user
            if _model_has_field(PatientArchive, "updated_by"):
                archive.updated_by = user
            archive.save()
            try:
                archive_form.save_m2m()
            except Exception:
                pass
            files_to_save = (
                attachment_form.cleaned_data.get("files")
                or []
            )
            description = (
                attachment_form.cleaned_data.get("description")
                or config["description"]
            ).strip()
            for uploaded_file in files_to_save:
                create_kwargs: Dict[str, Any] = {
                    "archive": archive,
                    "file": uploaded_file,
                    "description": description,
                }
                if _model_has_field(
                    ArchiveAttachment,
                    "uploaded_by",
                ):
                    create_kwargs["uploaded_by"] = user
                ArchiveAttachment.objects.create(**create_kwargs)
    except ValidationError as exc:
        message = (
            str(getattr(exc, "message", ""))
            or str(exc)
            or "Validation error."
        )
        return _json_error(message, status=400)
    except Exception as exc:
        logger.exception(
            "Unexpected error during quick clinical handoff: %s",
            exc,
        )
        return _json_error(
            "Unexpected error while sending the clinical file.",
            status=500,
        )
    return _json_success(
        "Clinical file sent to the doctor successfully.",
        extra={
            "archive_id": archive.pk,
            "patient_id": patient.pk,
            "doctor_id": doctor.pk,
            "clinical_type": clinical_type,
        },
    )

# =========================
# Create
# =========================
class _VoiceFormInvalid(Exception):
    """Internal sentinel used to rollback atomic transaction when voice form is invalid."""


@login_required
@permission_required(PERM_ADD_ARCHIVE, raise_exception=True)
@require_http_methods(["GET", "POST"])
def create_archive(request: HttpRequest) -> HttpResponse:
    """
    Create a new archive with:
    - optional multiple attachments
    - optional voice note

    Fixes included:
    - Robust extraction of attachments even if input name differs
    - Ensures attachment form sees files under "files"
    - Ensures voice form sees file under "audio" even if input name differs
    - Voice validated only after archive exists
    - Handles "title" collision between archive title and voice title
    - Uses attachment_form.cleaned_data['files'] for saving (critical)
    - If user enters voice title without uploading audio -> show clear error
    """
    user = request.user
    role = _get_role(user)

    if not (getattr(user, "is_superuser", False) or role in ROLE_CREATE_ALLOWED):
        raise Http404("Not found.")

    if request.method == "POST":
        archive_data, voice_data = _fix_title_collision(request.POST)

        extracted_files = _extract_attachment_files(request)
        patched_files = _patch_files_for_attachment_form(request, extracted_files)
        patched_voice_files = _patch_files_for_voice_form(request)

        # Optional: provide a safe default description when attachments exist (helps UX + avoids blanks)
        attachment_post = request.POST.copy()
        if extracted_files and not (attachment_post.get("description") or "").strip():
            if len(extracted_files) == 1:
                attachment_post["description"] = os.path.splitext(extracted_files[0].name or "")[0] or "Attachment"
            else:
                attachment_post["description"] = "Attachments"

        archive_form = PatientArchiveForm(archive_data, user=user)
        attachment_form = ArchiveAttachmentForm(attachment_post, patched_files)
        voice_form = ArchiveVoiceNoteForm(voice_data, patched_voice_files)

        attachments_present = bool(extracted_files)

        voice_file_present = _voice_file_present(request)
        voice_title = (voice_data.get("title") or "").strip()
        voice_present = bool(voice_file_present or voice_title)

        if attachments_present and not user.has_perm(PERM_ADD_ATTACHMENT):
            message = "You do not have permission to add archive attachments."
            if _is_ajax(request):
                return _json_error(message, status=403)
            raise PermissionDenied(message)

        if voice_present and not user.has_perm(PERM_ADD_VOICE_NOTE):
            message = "You do not have permission to add archive voice notes."
            if _is_ajax(request):
                return _json_error(message, status=403)
            raise PermissionDenied(message)

        # Early-friendly validation: voice title without audio
        voice_invalid_early = False
        if voice_title and not voice_file_present:
            voice_invalid_early = True
            voice_form.add_error("audio", "Please upload a voice file or clear the voice title.")

        archive_valid = archive_form.is_valid()

        attachments_valid = True
        if attachments_present:
            attachments_valid = attachment_form.is_valid()

        if voice_invalid_early or (not archive_valid) or (attachments_present and not attachments_valid):
            if _is_ajax(request):
                return _json_error(
                    "Validation failed.",
                    status=400,
                    extra={
                        "archive_errors": _form_errors_json(archive_form),
                        "attachment_errors": _form_errors_json(attachment_form) if attachments_present else {},
                        "voice_errors": _form_errors_json(voice_form) if voice_invalid_early else {},
                    },
                )

            if voice_invalid_early:
                messages.error(request, "🎙️ Please upload a voice file or clear the voice title.")
                _add_form_errors_as_messages(request, voice_form, "🎙️")

            if not archive_valid:
                messages.error(request, "❌ Please check the archive form fields.")
                _add_form_errors_as_messages(request, archive_form, "❌")

            if attachments_present and not attachments_valid:
                messages.error(request, "📎 Please check attachment fields.")
                _add_form_errors_as_messages(request, attachment_form, "📎")

            doctors, patients = _get_doctors_patients_for_user(user)
            return render(
                request,
                "medical_archive/create_archive.html",
                {
                    "archive_form": archive_form,
                    "attachment_form": attachment_form,
                    "voice_form": voice_form,
                    "doctors": doctors,
                    "patients": patients,
                },
            )

        # Save everything atomically
        try:
            with transaction.atomic():
                archive = archive_form.save(commit=False)

                # Auto-fill doctor for doctor role if not set by the form
                if (
                    role == "doctor"
                    and _model_has_field(PatientArchive, "doctor")
                    and not getattr(archive, "doctor_id", None)
                ):
                    try:
                        archive.doctor = Doctor.objects.select_related("user").get(user=user)
                    except Doctor.DoesNotExist:
                        raise ValidationError("Doctor profile not found for this user.")

                if _model_has_field(PatientArchive, "created_by") and not getattr(archive, "created_by_id", None):
                    archive.created_by = user
                if _model_has_field(PatientArchive, "updated_by"):
                    archive.updated_by = user

                archive.save()
                try:
                    archive_form.save_m2m()
                except Exception:
                    pass

                # Attachments - IMPORTANT: save only cleaned_data["files"]
                if attachments_present:
                    files_to_save = attachment_form.cleaned_data.get("files") or []
                    description = (attachment_form.cleaned_data.get("description") or "").strip()
                    has_uploaded_by = _model_has_field(ArchiveAttachment, "uploaded_by")

                    for f in files_to_save:
                        try:
                            create_kwargs: Dict[str, Any] = {
                                "archive": archive,
                                "file": f,
                                "description": description,
                            }
                            if has_uploaded_by:
                                create_kwargs["uploaded_by"] = user
                            ArchiveAttachment.objects.create(**create_kwargs)
                        except ValidationError as ve:
                            raise ValidationError(f"Attachment '{getattr(f, 'name', 'file')}' error: {ve}")

                # Voice note - validate AFTER archive exists
                if voice_present:
                    voice_form.instance.archive = archive

                    if _model_has_field(ArchiveVoiceNote, "recorded_by"):
                        try:
                            voice_form.instance.recorded_by = user
                        except Exception:
                            pass

                    if not voice_form.is_valid():
                        raise _VoiceFormInvalid()

                    voice_obj: ArchiveVoiceNote = voice_form.save(commit=False)
                    voice_obj.archive = archive
                    if _model_has_field(ArchiveVoiceNote, "recorded_by") and not getattr(voice_obj, "recorded_by_id", None):
                        voice_obj.recorded_by = user
                    voice_obj.save()

        except _VoiceFormInvalid:
            if _is_ajax(request):
                return _json_error(
                    "Voice note validation failed.",
                    status=400,
                    extra={"voice_errors": _form_errors_json(voice_form)},
                )

            messages.error(request, "🎙️ Please check voice note fields.")
            _add_form_errors_as_messages(request, voice_form, "🎙️")

            doctors, patients = _get_doctors_patients_for_user(user)
            return render(
                request,
                "medical_archive/create_archive.html",
                {
                    "archive_form": archive_form,
                    "attachment_form": attachment_form,
                    "voice_form": voice_form,
                    "doctors": doctors,
                    "patients": patients,
                },
            )

        except ValidationError as ve:
            msg = str(getattr(ve, "message", "")) or str(ve) or "Validation error."
            if _is_ajax(request):
                return _json_error(msg, status=400)
            messages.error(request, f"❌ {msg}")

            doctors, patients = _get_doctors_patients_for_user(user)
            return render(
                request,
                "medical_archive/create_archive.html",
                {
                    "archive_form": archive_form,
                    "attachment_form": attachment_form,
                    "voice_form": voice_form,
                    "doctors": doctors,
                    "patients": patients,
                },
            )

        except Exception as e:
            logger.exception("Unexpected error while saving archive: %s", e)
            if _is_ajax(request):
                return _json_error("Unexpected error while saving.", status=500, extra={"detail": str(e)})
            messages.error(request, "❌ Unexpected error while saving. Please try again.")

            doctors, patients = _get_doctors_patients_for_user(user)
            return render(
                request,
                "medical_archive/create_archive.html",
                {
                    "archive_form": archive_form,
                    "attachment_form": attachment_form,
                    "voice_form": voice_form,
                    "doctors": doctors,
                    "patients": patients,
                },
            )

        redirect_url = reverse("medical_archive:archive_list")
        if _is_ajax(request):
            return _json_success("Archive saved successfully.", redirect_url=redirect_url)

        messages.success(request, "✅ Archive saved successfully.")
        return redirect("medical_archive:archive_list")

    # GET
    archive_form = PatientArchiveForm(user=request.user)
    attachment_form = ArchiveAttachmentForm()
    voice_form = ArchiveVoiceNoteForm()
    doctors, patients = _get_doctors_patients_for_user(request.user)

    return render(
        request,
        "medical_archive/create_archive.html",
        {
            "archive_form": archive_form,
            "attachment_form": attachment_form,
            "voice_form": voice_form,
            "doctors": doctors,
            "patients": patients,
        },
    )


# =========================
# Detail
# =========================
@login_required
@permission_required(PERM_VIEW_ARCHIVE, raise_exception=True)
def archive_detail(request: HttpRequest, archive_id: int) -> HttpResponse:
    archive = get_object_or_404(
        PatientArchive.objects.select_related("patient", "patient__user", "doctor", "doctor__user")
        .prefetch_related("attachments", "voice_notes"),
        pk=archive_id,
    )

    if not _is_authorized_for_archive(request.user, archive):
        raise Http404("Not found.")

    can_view_attachments = request.user.has_perm(PERM_VIEW_ATTACHMENT)
    can_view_voice_notes = request.user.has_perm(PERM_VIEW_VOICE_NOTE)

    attachments_mgr = getattr(archive, "attachments", None) if can_view_attachments else None
    voice_mgr = getattr(archive, "voice_notes", None) if can_view_voice_notes else None

    attachments = (
        list(attachments_mgr.all().order_by("-uploaded_at"))
        if attachments_mgr is not None
        else []
    )
    voice_notes = (
        list(voice_mgr.all().order_by("-recorded_at"))
        if voice_mgr is not None
        else []
    )

    return render(
        request,
        "medical_archive/archive_detail.html",
        {
            "archive": archive,
            "attachments": attachments,
            "voice_notes": voice_notes,
            "can_view_attachments": can_view_attachments,
            "can_view_voice_notes": can_view_voice_notes,
        },
    )


# =========================
# Export PDF (ReportLab) - FIXED LAYOUT + ARABIC FONTS
# =========================
@login_required
@permission_required(PERM_VIEW_ARCHIVE, raise_exception=True)
def export_archive_pdf(request: HttpRequest, archive_id: int) -> FileResponse:
    """
    Fixes:
    - No overlap for long strings (UUID names) via Paragraph cells + wordWrap
    - Arabic "black squares" fixed by embedding a TTF font (DejaVu/Arial/Noto/Amiri)
    - Professional attachments details: type + size + shortened stored name
    """
    archive = get_object_or_404(
        PatientArchive.objects.select_related("patient", "doctor", "doctor__user")
        .prefetch_related("attachments", "voice_notes"),
        pk=archive_id,
    )

    if not _is_authorized_for_archive(request.user, archive):
        raise Http404("Not found.")

    patient_name = getattr(getattr(archive, "patient", None), "full_name", None) or "—"
    doctor_name = "—"
    doctor_username = "—"
    if getattr(archive, "doctor", None) and getattr(archive.doctor, "user", None):
        doctor_username = archive.doctor.user.username or "—"
        doctor_name = archive.doctor.user.get_full_name() or doctor_username or "—"

    notes_html = getattr(archive, "notes", "") or ""
    notes_text_raw = strip_tags(notes_html).replace("\r\n", "\n").strip() if notes_html else ""
    notes_text = _shape_text_for_pdf(notes_text_raw)

    attachments_mgr = (
        getattr(archive, "attachments", None)
        if request.user.has_perm(PERM_VIEW_ATTACHMENT)
        else None
    )
    voice_mgr = (
        getattr(archive, "voice_notes", None)
        if request.user.has_perm(PERM_VIEW_VOICE_NOTE)
        else None
    )
    attachments = list(attachments_mgr.all().order_by("-uploaded_at")) if attachments_mgr is not None else []
    voices = list(voice_mgr.all().order_by("-recorded_at")) if voice_mgr is not None else []

    latin_font, ar_font = _register_pdf_fonts()

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=2 * cm,
        rightMargin=2 * cm,
        topMargin=2 * cm,
        bottomMargin=2 * cm,
        title=f"Archive {archive_id}",
        author="ClinicHub",
    )

    base = getSampleStyleSheet()

    title_style = ParagraphStyle(
        "CH_Title",
        parent=base["Title"],
        fontName=latin_font,
        fontSize=18,
        leading=22,
        textColor=colors.black,
        alignment=TA_LEFT,
        spaceAfter=10,
    )

    h2_style = ParagraphStyle(
        "CH_H2",
        parent=base["Heading2"],
        fontName=latin_font,
        fontSize=12.5,
        leading=16,
        textColor=colors.black,
        spaceBefore=10,
        spaceAfter=8,
        alignment=TA_LEFT,
    )

    # Table cell styles (Paragraph enables wrapping)
    cell_style_latin = ParagraphStyle(
        "CH_Cell_L",
        parent=base["BodyText"],
        fontName=latin_font,
        fontSize=9.2,
        leading=12,
        textColor=colors.black,
        wordWrap="CJK",
    )
    cell_style_ar = ParagraphStyle(
        "CH_Cell_AR",
        parent=base["BodyText"],
        fontName=ar_font,
        fontSize=9.2,
        leading=12,
        textColor=colors.black,
        wordWrap="CJK",
        alignment=TA_RIGHT,
    )

    small_latin = ParagraphStyle("CH_Small_L", parent=cell_style_latin, fontSize=8.6, leading=11)
    small_ar = ParagraphStyle("CH_Small_AR", parent=cell_style_ar, fontSize=8.6, leading=11)

    notes_style = ParagraphStyle(
        "CH_Notes",
        parent=base["BodyText"],
        fontName=(ar_font if _has_arabic(notes_text_raw) else latin_font),
        fontSize=10.5,
        leading=15,
        alignment=TA_RIGHT if _has_arabic(notes_text_raw) else TA_LEFT,
        wordWrap="CJK",
    )

    def P(text: str, small: bool = False) -> Paragraph:
        txt = text or "—"
        shaped = _shape_text_for_pdf(txt)
        style = (small_ar if small else cell_style_ar) if _has_arabic(txt) else (small_latin if small else cell_style_latin)
        return Paragraph(_p_text(shaped), style)

    story: List[Any] = []
    story.append(Paragraph("Medical Record Export", title_style))

    doctor_display = doctor_name
    # If Arabic font not available, keep name and also show username as safe fallback
    if _has_arabic(doctor_name) and (ar_font == "Helvetica"):
        doctor_display = f"{doctor_name} ({doctor_username})"

    meta_rows = [
        [P("Archive ID", small=True), P(f"ARCH-{archive.id:04d}", small=True)],
        [P("Title", small=True), P(getattr(archive, "title", "") or "—")],
        [P("Type", small=True), P(archive.get_archive_type_display() if hasattr(archive, "get_archive_type_display") else str(getattr(archive, "archive_type", "—")))],
        [P("Status", small=True), P(archive.get_status_display() if hasattr(archive, "get_status_display") else str(getattr(archive, "status", "—")))],
        [P("Critical", small=True), P("YES" if getattr(archive, "is_critical", False) else "NO", small=True)],
        [P("Created", small=True), P(_fmt_dt(getattr(archive, "created_at", None)), small=True)],
        [P("Updated", small=True), P(_fmt_dt(getattr(archive, "updated_at", None)), small=True)],
        [P("Patient", small=True), P(patient_name)],
        [P("Doctor", small=True), P(doctor_display)],
    ]

    meta_table = Table(meta_rows, colWidths=[4.2 * cm, 11.8 * cm])
    meta_table.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LINEBELOW", (0, 0), (-1, -1), 0.25, colors.lightgrey),
                ("ROWBACKGROUNDS", (0, 0), (-1, -1), [colors.white, colors.HexColor("#fafafa")]),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ]
        )
    )
    story.append(meta_table)
    story.append(Spacer(1, 14))

    story.append(Paragraph("Clinical Notes", h2_style))
    story.append(Paragraph(_p_text(notes_text or "—"), notes_style))
    story.append(Spacer(1, 14))

    story.append(Paragraph(f"Attachments ({len(attachments)})", h2_style))
    if attachments:
        att_rows = [[P("#", small=True), P("Name", small=True), P("Details", small=True), P("Uploaded", small=True)]]

        for idx, a in enumerate(attachments, start=1):
            desc = (getattr(a, "description", "") or "").strip()
            file_name = os.path.basename(getattr(getattr(a, "file", None), "name", "") or "") or "—"
            short_name = _shorten_middle(file_name, max_len=44)
            ext = os.path.splitext(file_name)[1].lstrip(".").upper() or "FILE"

            size_str = "—"
            try:
                size_val = getattr(getattr(a, "file", None), "size", None)
                if size_val is not None:
                    size_str = filesizeformat(size_val)
            except Exception:
                size_str = "—"

            display_name = desc or f"Attachment {idx} ({ext})"
            details = f"{ext} • {size_str} • {short_name}"

            when = getattr(a, "uploaded_at", None)
            when_str = when.strftime("%Y-%m-%d") if when else "—"

            att_rows.append(
                [
                    P(str(idx), small=True),
                    P(display_name),
                    P(details, small=True),
                    P(when_str, small=True),
                ]
            )

        att_table = Table(att_rows, colWidths=[1.0 * cm, 6.0 * cm, 6.0 * cm, 2.0 * cm], repeatRows=1)
        att_table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e8f0fe")),
                    ("GRID", (0, 0), (-1, -1), 0.25, colors.lightgrey),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#fafafa")]),
                    ("LEFTPADDING", (0, 0), (-1, -1), 5),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                    ("TOPPADDING", (0, 0), (-1, -1), 4),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ]
            )
        )
        story.append(att_table)
    else:
        story.append(Paragraph("—", cell_style_latin))

    story.append(Spacer(1, 14))

    story.append(Paragraph(f"Voice Notes ({len(voices)})", h2_style))
    if voices:
        v_rows = [[P("#", small=True), P("Title", small=True), P("Recorded", small=True), P("Duration (s)", small=True)]]

        for idx, v in enumerate(voices, start=1):
            title = getattr(v, "title", "") or "Voice Note"
            when = getattr(v, "recorded_at", None)
            when_str = when.strftime("%Y-%m-%d") if when else "—"
            dur = getattr(v, "duration_seconds", None)

            v_rows.append(
                [
                    P(str(idx), small=True),
                    P(title),
                    P(when_str, small=True),
                    P(str(dur) if dur is not None else "—", small=True),
                ]
            )

        v_table = Table(v_rows, colWidths=[1.0 * cm, 9.0 * cm, 3.5 * cm, 2.5 * cm], repeatRows=1)
        v_table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e8f5e9")),
                    ("GRID", (0, 0), (-1, -1), 0.25, colors.lightgrey),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#fafafa")]),
                    ("LEFTPADDING", (0, 0), (-1, -1), 5),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                    ("TOPPADDING", (0, 0), (-1, -1), 4),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ]
            )
        )
        story.append(v_table)
    else:
        story.append(Paragraph("—", cell_style_latin))

    doc.build(story)
    buf.seek(0)

    filename = f"archive-{archive.id:04d}.pdf"
    return FileResponse(buf, as_attachment=True, filename=filename, content_type="application/pdf")


# =========================
# Edit
# =========================
@login_required
@permission_required(PERM_CHANGE_ARCHIVE, raise_exception=True)
@require_http_methods(["GET", "POST"])
def edit_archive(request: HttpRequest, archive_id: int) -> HttpResponse:
    archive = get_object_or_404(
        PatientArchive.objects.select_related("doctor", "doctor__user", "patient", "patient__user"),
        pk=archive_id,
    )

    if not _can_edit_archive(request.user, archive):
        raise Http404("Not found.")

    if request.method == "POST":
        form = PatientArchiveForm(request.POST, instance=archive, user=request.user)
        if form.is_valid():
            edited = form.save(commit=False)

            if _model_has_field(PatientArchive, "updated_by"):
                edited.updated_by = request.user

            # Lock ownership for doctors (no switching patient/doctor)
            if _get_role(request.user) == "doctor":
                edited.patient = archive.patient
                if _model_has_field(PatientArchive, "doctor"):
                    edited.doctor = archive.doctor

            edited.save()
            try:
                form.save_m2m()
            except Exception:
                pass

            messages.success(request, "✅ Archive updated successfully.")
            return redirect("medical_archive:archive_detail", archive.id)

        messages.error(request, "❌ Please correct the errors below.")
    else:
        form = PatientArchiveForm(instance=archive, user=request.user)

    return render(request, "medical_archive/edit_archive.html", {"form": form, "archive": archive})


# =========================
# Delete
# =========================
@login_required
@permission_required(PERM_DELETE_ARCHIVE, raise_exception=True)
@require_http_methods(["GET", "POST"])
def delete_archive(request: HttpRequest, archive_id: int) -> HttpResponse:
    archive = get_object_or_404(
        PatientArchive.objects.select_related("doctor", "doctor__user"),
        pk=archive_id,
    )

    if not _can_edit_archive(request.user, archive):
        raise Http404("Not found.")

    if request.method == "POST":
        archive.delete()
        messages.success(request, "🗑️ Archive deleted successfully.")
        return redirect("medical_archive:archive_list")

    return render(request, "medical_archive/delete_archive.html", {"archive": archive})


# =========================
# Download Attachment
# =========================
@login_required
@permission_required(
    (PERM_VIEW_ARCHIVE, PERM_VIEW_ATTACHMENT),
    raise_exception=True,
)
def download_attachment(request: HttpRequest, attachment_id: int) -> FileResponse:
    attachment = get_object_or_404(
        ArchiveAttachment.objects.select_related(
            "archive",
            "archive__patient",
            "archive__patient__user",
            "archive__doctor",
            "archive__doctor__user",
        ),
        pk=attachment_id,
    )

    if not _is_authorized_for_archive(request.user, attachment.archive):
        raise Http404("Not found.")

    if not attachment.file or not getattr(attachment.file, "name", None):
        raise Http404("File not found.")

    filename = os.path.basename(attachment.file.name)

    try:
        fh = attachment.file.open("rb")
    except Exception:
        raise Http404("File not available.")

    return FileResponse(fh, as_attachment=True, filename=filename)


# =========================
# Download Voice Note
# =========================
@login_required
@permission_required(
    (PERM_VIEW_ARCHIVE, PERM_VIEW_VOICE_NOTE),
    raise_exception=True,
)
def download_voice_note(request: HttpRequest, voice_id: int) -> FileResponse:
    voice = get_object_or_404(
        ArchiveVoiceNote.objects.select_related(
            "archive",
            "archive__patient",
            "archive__patient__user",
            "archive__doctor",
            "archive__doctor__user",
        ),
        pk=voice_id,
    )

    if not _is_authorized_for_archive(request.user, voice.archive):
        raise Http404("Not found.")

    if not voice.audio or not getattr(voice.audio, "name", None):
        raise Http404("Audio not found.")

    filename = os.path.basename(voice.audio.name)

    try:
        fh = voice.audio.open("rb")
    except Exception:
        raise Http404("Audio not available.")

    return FileResponse(fh, as_attachment=True, filename=filename)
