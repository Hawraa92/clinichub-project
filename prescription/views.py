# prescription/views.py
from __future__ import annotations

import base64
import binascii
import io
import logging
from datetime import date, datetime
from typing import Optional
from urllib.parse import quote

import qrcode
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.files.base import ContentFile
from django.core.signing import BadSignature, SignatureExpired, dumps, loads
from django.db import IntegrityError, transaction
from django.http import FileResponse, Http404, HttpResponse, HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import NoReverseMatch, reverse
from django.utils import timezone
from django.views.decorators.cache import cache_control
from django.views.decorators.http import require_GET, require_http_methods

from appointments.models import Appointment
from doctor.models import Doctor
from medical_archive.models import ArchiveAttachment, ArchiveVoiceNote, PatientArchive

from .forms import MedicationFormSet, PrescriptionForm
from .models import Prescription

logger = logging.getLogger(__name__)


# =========================
# Helpers / Model Introspection
# =========================
def _model_has_field(model, field_name: str) -> bool:
    try:
        model._meta.get_field(field_name)
        return True
    except Exception:
        return False


def _user_in_group(user, group_name: str) -> bool:
    try:
        return user.groups.filter(name=group_name).exists()
    except Exception:
        return False


def _role(user) -> str:
    return str(getattr(user, "role", "") or "").lower()


def _secretary_can_access_prescriptions() -> bool:
    """
    افتراضياً: السكرتيرة ما تشوف الوصفات.
    فعّليها إذا تريدين: PRESCRIPTION_SECRETARY_CAN_VIEW = True
    """
    return bool(getattr(settings, "PRESCRIPTION_SECRETARY_CAN_VIEW", False))


def _admin_can_access_prescriptions() -> bool:
    """
    إذا عندك role=admin وتريدين تمنعينه أيضاً، خليها False.
    الافتراضي True.
    """
    return bool(getattr(settings, "PRESCRIPTION_ADMIN_CAN_VIEW", True))


def _force_archive_enabled() -> bool:
    """
    الأرشفة الآلية 100% (بدون الاعتماد على checkbox)
    الافتراضي True حتى يطابق نص Phase 3.
    """
    return bool(getattr(settings, "PRESCRIPTION_FORCE_ARCHIVE", True))


def _can_view_prescription(user, p: Prescription) -> bool:
    """
    RBAC:
      - superuser: كل شيء
      - doctor: وصفاته فقط
      - patient: وصفاته (عبر الموعد المرتبط)
      - secretary/admin: اختياري عبر settings
    """
    if getattr(user, "is_superuser", False):
        return True

    r = _role(user)

    if r == "secretary" or _user_in_group(user, "Secretaries"):
        return _secretary_can_access_prescriptions()

    if r == "admin":
        return _admin_can_access_prescriptions()

    if r == "doctor" or _user_in_group(user, "Doctors"):
        try:
            return getattr(p.doctor, "user_id", None) == getattr(user, "id", None)
        except Exception:
            return False

    if r == "patient" or _user_in_group(user, "Patients"):
        appt = getattr(p, "appointment", None)
        patient = getattr(appt, "patient", None) if appt else None
        return bool(patient and getattr(patient, "user_id", None) == getattr(user, "id", None))

    return False


def _can_manage_prescription(user, p: Prescription) -> bool:
    """
    edit/delete: نفس view تقريباً.
    """
    if getattr(user, "is_superuser", False):
        return True

    r = _role(user)

    if r == "secretary" or _user_in_group(user, "Secretaries"):
        return _secretary_can_access_prescriptions()

    if r == "admin":
        return _admin_can_access_prescriptions()

    if r == "doctor" or _user_in_group(user, "Doctors"):
        return getattr(p.doctor, "user_id", None) == getattr(user, "id", None)

    return False


def _verify_max_age_seconds() -> int:
    """مدة صلاحية رمز التحقق (افتراضي: 365 يومًا)."""
    days = int(getattr(settings, "PRESCRIPTION_VERIFY_MAX_AGE_DAYS", 365))
    return max(1, days) * 24 * 60 * 60


def _public_download_enabled() -> bool:
    """
    هل نسمح بتحميل PDF من صفحة التحقق العامة؟
    الافتراضي False لأن الـ PDF بيه معلومات حساسة.
    """
    return bool(getattr(settings, "PRESCRIPTION_PUBLIC_DOWNLOAD", False))


def _token_fingerprint(token: str) -> str:
    """بصمة قصيرة للتوكن للعرض العام بدون كشف أي بيانات."""
    try:
        last = token.split(":")[-1]
        return last[:12]
    except Exception:
        return ""


def _issued_display(p: Prescription) -> str:
    """
    عرض تاريخ الإصدار بشكل آمن سواء كان DateTime أو Date.
    """
    candidates = []
    for f in ("date_issued", "issued_at", "created_at"):
        if hasattr(p, f):
            candidates.append(getattr(p, f, None))

    v = next((x for x in candidates if x), None)
    if not v:
        v = timezone.now()

    try:
        if isinstance(v, datetime):
            v = timezone.localtime(v) if timezone.is_aware(v) or settings.USE_TZ else v
            return v.strftime("%Y-%m-%d %H:%M")
        if isinstance(v, date):
            return v.strftime("%Y-%m-%d")
    except Exception:
        pass

    return str(v)


def _build_verify_url(request, p: Prescription) -> Optional[str]:
    """يبني رابط تحقق متوافق مع verify view."""
    try:
        token = (
            p.make_verification_token()
            if hasattr(p, "make_verification_token")
            else dumps({"pid": p.pk}, salt="rx.verify")
        )
        return request.build_absolute_uri(reverse("prescription:verify", kwargs={"token": token}))
    except Exception as e:
        logger.warning("Failed building verify URL for RX %s: %s", getattr(p, "pk", None), e)
        return None


def _qr_b64_from_url(url: str) -> Optional[str]:
    """توليد QR Base64 لعرضه داخل تمبلت التفاصيل."""
    try:
        qr = qrcode.QRCode(
            version=1,
            box_size=6,
            border=2,
            error_correction=qrcode.constants.ERROR_CORRECT_M,
        )
        qr.add_data(url)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return base64.b64encode(buf.getvalue()).decode("ascii")
    except Exception:
        return None


def _safe_prescription_form(*args, **kwargs):
    """
    ينشئ PrescriptionForm ويمرر user إذا الفورم يدعمه.
    إذا الفورم ما يقبل user، نحذفها ونعيد المحاولة بدون كسر.
    """
    try:
        return PrescriptionForm(*args, **kwargs)
    except TypeError:
        kwargs.pop("user", None)
        return PrescriptionForm(*args, **kwargs)


def _apply_force_archive_ui(form) -> None:
    """
    إذا الأرشفة إجبارية: نخلي checkbox ثابت (disabled).
    """
    try:
        if _force_archive_enabled() and "archive_prescription" in getattr(form, "fields", {}):
            f = form.fields["archive_prescription"]
            f.initial = True
            f.disabled = True
            if getattr(f, "help_text", None):
                f.help_text = "Archiving is enforced by system policy."
    except Exception:
        pass


def _appointments_for_user(user):
    """
    يرجّع مواعيد مسموحة حسب الدور.
    - superuser: الكل
    - doctor: مواعيده فقط
    """
    qs = Appointment.objects.select_related("patient__user", "doctor__user")

    if getattr(user, "is_superuser", False):
        return qs.all().order_by("scheduled_time", "pk")

    return qs.filter(doctor__user=user).order_by("scheduled_time", "pk")


def _appointments_without_prescriptions(appt_qs):
    """
    آمن بدون الاعتماد على reverse relation name.
    """
    try:
        used_ids = Prescription.objects.exclude(appointment_id__isnull=True).values_list("appointment_id", flat=True)
        return appt_qs.exclude(id__in=used_ids)
    except Exception:
        return appt_qs


def _has_explicit_appointment_selection(request, forced_appointment_id: Optional[int]) -> bool:
    """
    هل المستخدم اختار موعدًا بشكل صريح؟
    - من route parameter
    - أو query/post appointment
    """
    if forced_appointment_id:
        return True

    appt_id_param = request.GET.get("appointment") or request.POST.get("appointment")
    return bool(appt_id_param)


def _pick_selected_appointment(request, appt_qs, forced_appointment_id: Optional[int]) -> Optional[Appointment]:
    """
    لا نختار أول موعد تلقائيًا عند فتح New Prescription.
    نختار الموعد فقط إذا:
    - كان مفروضًا من الرابط
    - أو مختارًا صراحةً من query/post
    """
    if forced_appointment_id:
        selected = appt_qs.filter(pk=forced_appointment_id).first()
        if not selected:
            raise Http404("Appointment not found or not allowed.")
        return selected

    appt_id_param = request.GET.get("appointment") or request.POST.get("appointment")
    if appt_id_param:
        selected = appt_qs.filter(pk=appt_id_param).first()
        if selected:
            return selected

    return None


def _next_appointment_after(appt_qs, selected: Optional[Appointment]) -> Optional[Appointment]:
    if not selected or not getattr(selected, "scheduled_time", None):
        return None
    return appt_qs.filter(scheduled_time__gt=selected.scheduled_time).first()


# =========================
# Voice helpers
# =========================
def _configured_voice_field_name() -> Optional[str]:
    value = str(getattr(settings, "PRESCRIPTION_VOICE_FIELD_NAME", "") or "").strip()
    return value or None


def _possible_voice_field_names() -> tuple[str, ...]:
    configured = _configured_voice_field_name()
    names: list[str] = []

    if configured:
        names.append(configured)

    names.extend(
        [
            "voice_note",
            "voice_file",
            "audio_file",
            "voice_recording",
            "recording",
            "audio_note",
            "voice_message",
            "audio",
            "voice",
        ]
    )

    unique: list[str] = []
    for name in names:
        if name and name not in unique:
            unique.append(name)
    return tuple(unique)


def _possible_voice_request_keys() -> tuple[str, ...]:
    extra = getattr(settings, "PRESCRIPTION_VOICE_REQUEST_KEYS", None) or []
    names = list(_possible_voice_field_names()) + [
        "voice_note_data",
        "voice_data",
        "audio_data",
        "recording_data",
        "voice_blob",
        "audio_blob",
        "recorded_audio",
        "recorded_voice",
        "voice_note_base64",
        "audio_base64",
    ]

    for item in extra:
        item = str(item or "").strip()
        if item:
            names.append(item)

    unique: list[str] = []
    for name in names:
        if name and name not in unique:
            unique.append(name)
    return tuple(unique)


def _get_existing_prescription_voice_field_name() -> Optional[str]:
    for field_name in _possible_voice_field_names():
        if _model_has_field(Prescription, field_name):
            return field_name
    return None


def _filefield_has_content(field_obj) -> bool:
    try:
        return bool(field_obj and getattr(field_obj, "name", None))
    except Exception:
        return False


def _guess_audio_extension(filename: str = "", content_type: str = "") -> str:
    filename = (filename or "").strip().lower()
    content_type = (content_type or "").strip().lower()

    if "." in filename:
        ext = "." + filename.rsplit(".", 1)[-1]
        if len(ext) <= 8:
            return ext

    mapping = {
        "audio/webm": ".webm",
        "video/webm": ".webm",
        "audio/wav": ".wav",
        "audio/x-wav": ".wav",
        "audio/mpeg": ".mp3",
        "audio/mp3": ".mp3",
        "audio/mp4": ".m4a",
        "audio/x-m4a": ".m4a",
        "video/mp4": ".m4a",
        "audio/aac": ".aac",
        "audio/ogg": ".ogg",
        "audio/oga": ".ogg",
        "application/ogg": ".ogg",
    }
    return mapping.get(content_type, ".webm")


def _decode_base64_audio(raw_value: str) -> tuple[Optional[bytes], Optional[str]]:
    value = str(raw_value or "").strip()
    if not value:
        return None, None

    content_type = ""
    payload = value

    if value.startswith("data:") and "," in value:
        header, payload = value.split(",", 1)
        try:
            content_type = header[5:].split(";", 1)[0].strip().lower()
        except Exception:
            content_type = ""

    payload = "".join(payload.split())
    if not payload or len(payload) < 32:
        return None, None

    missing_padding = len(payload) % 4
    if missing_padding:
        payload += "=" * (4 - missing_padding)

    try:
        decoded = base64.b64decode(payload, validate=False)
    except (binascii.Error, ValueError):
        return None, None

    if not decoded:
        return None, None

    return decoded, _guess_audio_extension(content_type=content_type)


def _save_bytes_to_prescription_voice_field(
    prescription: Prescription,
    field_name: str,
    audio_bytes: bytes,
    *,
    filename: str,
) -> bool:
    if not audio_bytes:
        return False

    if not _model_has_field(Prescription, field_name):
        return False

    field_file = getattr(prescription, field_name, None)
    if field_file is None:
        return False

    old_name = getattr(field_file, "name", None)

    try:
        field_file.save(filename, ContentFile(audio_bytes), save=False)
        prescription.save(update_fields=[field_name])

        new_name = getattr(getattr(prescription, field_name, None), "name", None)
        if old_name and new_name and old_name != new_name:
            try:
                getattr(prescription, field_name).storage.delete(old_name)
            except Exception:
                pass

        return True
    except Exception as e:
        logger.warning(
            "RX %s: failed saving voice content into field '%s': %s",
            getattr(prescription, "pk", None),
            field_name,
            e,
        )
        return False


def _save_voice_from_value_to_prescription(
    prescription: Prescription,
    field_name: str,
    value,
) -> bool:
    if value is None:
        return False

    # Uploaded file-like object
    if hasattr(value, "read"):
        try:
            raw = value.read()
            if hasattr(value, "seek"):
                try:
                    value.seek(0)
                except Exception:
                    pass

            if not raw:
                return False

            ext = _guess_audio_extension(
                filename=getattr(value, "name", "") or "",
                content_type=getattr(value, "content_type", "") or "",
            )
            filename = f"rx_voice_{getattr(prescription, 'pk', 'new')}{ext}"
            return _save_bytes_to_prescription_voice_field(
                prescription,
                field_name,
                raw,
                filename=filename,
            )
        except Exception as e:
            logger.warning(
                "RX %s: failed reading uploaded voice object for field '%s': %s",
                getattr(prescription, "pk", None),
                field_name,
                e,
            )
            return False

    # Base64 string / data URI
    if isinstance(value, str):
        audio_bytes, ext = _decode_base64_audio(value)
        if not audio_bytes:
            return False

        filename = f"rx_voice_{getattr(prescription, 'pk', 'new')}{ext or '.webm'}"
        return _save_bytes_to_prescription_voice_field(
            prescription,
            field_name,
            audio_bytes,
            filename=filename,
        )

    return False


def _persist_request_voice_to_prescription(request, prescription: Prescription, form=None) -> bool:
    """
    يحاول حفظ الصوت داخل الوصفة من أكثر من مصدر:
    1) form.cleaned_data
    2) request.FILES
    3) request.POST (base64 / data URI)
    وإذا ماكو payload جديد لكنه محفوظ أصلًا داخل الموديل، يعتبر النجاح قائم.
    """
    field_name = _get_existing_prescription_voice_field_name()
    if not field_name:
        logger.info(
            "RX %s: no known voice FileField found on Prescription model. "
            "Set PRESCRIPTION_VOICE_FIELD_NAME if your field name is custom.",
            getattr(prescription, "pk", None),
        )
        return False

    candidate_keys = [field_name, *_possible_voice_request_keys()]

    # 1) حاول من cleaned_data
    cleaned_data = getattr(form, "cleaned_data", {}) if form is not None else {}
    if isinstance(cleaned_data, dict):
        checked: set[str] = set()
        for key in candidate_keys:
            if key in checked:
                continue
            checked.add(key)

            if key not in cleaned_data:
                continue

            value = cleaned_data.get(key)
            if _save_voice_from_value_to_prescription(prescription, field_name, value):
                logger.info(
                    "RX %s: voice saved from form.cleaned_data['%s'] into '%s'.",
                    getattr(prescription, "pk", None),
                    key,
                    field_name,
                )
                return True

    # 2) حاول من request.FILES
    checked = set()
    for key in candidate_keys:
        if key in checked:
            continue
        checked.add(key)

        uploaded = request.FILES.get(key)
        if uploaded and _save_voice_from_value_to_prescription(prescription, field_name, uploaded):
            logger.info(
                "RX %s: voice saved from request.FILES['%s'] into '%s'.",
                getattr(prescription, "pk", None),
                key,
                field_name,
            )
            return True

    # 3) حاول من request.POST
    checked = set()
    for key in candidate_keys:
        if key in checked:
            continue
        checked.add(key)

        raw_value = request.POST.get(key)
        if raw_value and _save_voice_from_value_to_prescription(prescription, field_name, raw_value):
            logger.info(
                "RX %s: voice saved from request.POST['%s'] into '%s'.",
                getattr(prescription, "pk", None),
                key,
                field_name,
            )
            return True

    # 4) إذا موجود أصلًا داخل الموديل
    current_field_obj = getattr(prescription, field_name, None)
    if _filefield_has_content(current_field_obj):
        logger.info(
            "RX %s: voice already present in model field '%s'.",
            getattr(prescription, "pk", None),
            field_name,
        )
        return True

    logger.warning(
        "RX %s: no voice payload found to persist for model field '%s'.",
        getattr(prescription, "pk", None),
        field_name,
    )
    return False


def _schedule_archive_after_commit(prescription_id: int, user, archive_flag: bool) -> None:
    """
    يؤجل الأرشفة إلى ما بعد نجاح الـ commit حتى نقرأ الملفات من قاعدة البيانات
    وهي محفوظة فعليًا.
    """
    if not archive_flag:
        return

    def _callback() -> None:
        try:
            fresh = (
                Prescription.objects.select_related("doctor__user", "appointment__patient__user")
                .filter(pk=prescription_id)
                .first()
            )
            if not fresh:
                logger.warning("RX %s: cannot archive after commit because object no longer exists.", prescription_id)
                return

            _archive_prescription_if_needed(
                prescription=fresh,
                user=user,
                archive_flag=True,
            )
        except Exception as e:
            logger.exception("RX %s: archive after commit failed: %s", prescription_id, e)

    try:
        transaction.on_commit(_callback)
    except Exception:
        _callback()


# =========================
# Assets / Archive helpers
# =========================
def _ensure_assets_after_medications(p: Prescription, *, force_pdf: bool = True) -> None:
    """
    بعد حفظ medications، نضمن توليد PDF صحيح (و QR إذا ناقص).
    """
    if not getattr(p, "pk", None):
        return

    old_pdf_name = p.pdf_file.name if getattr(p, "pdf_file", None) else None
    old_qr_name = p.qr_code.name if getattr(p, "qr_code", None) else None

    try:
        if hasattr(p, "regenerate_assets"):
            p.regenerate_assets(force_qr=False, force_pdf=force_pdf)  # type: ignore[attr-defined]
        else:
            if not getattr(p, "qr_code", None) and hasattr(p, "generate_qr_code"):
                p.generate_qr_code()

            if force_pdf and hasattr(p, "medications") and p.medications.exists() and hasattr(p, "generate_pdf"):
                p.generate_pdf()
    except Exception as e:
        logger.warning("Post-medications asset generation failed for RX %s: %s", getattr(p, "pk", None), e)
        return

    update_fields: list[str] = []
    new_pdf_name = p.pdf_file.name if getattr(p, "pdf_file", None) else None
    new_qr_name = p.qr_code.name if getattr(p, "qr_code", None) else None

    if new_qr_name and new_qr_name != old_qr_name:
        update_fields.append("qr_code")
    if new_pdf_name and new_pdf_name != old_pdf_name:
        update_fields.append("pdf_file")

    if update_fields:
        try:
            p.save(update_fields=update_fields)
        except Exception as e:
            logger.warning("Saving updated assets failed for RX %s: %s", getattr(p, "pk", None), e)

    try:
        if old_pdf_name and new_pdf_name and old_pdf_name != new_pdf_name:
            try:
                p.pdf_file.storage.delete(old_pdf_name)
            except Exception:
                pass
    except Exception:
        pass

    try:
        if old_qr_name and new_qr_name and old_qr_name != new_qr_name:
            try:
                p.qr_code.storage.delete(old_qr_name)
            except Exception:
                pass
    except Exception:
        pass


def _upsert_archive_pdf_copy(archive: PatientArchive, prescription: Prescription, user) -> None:
    """
    نخزن نسخة PDF داخل ArchiveAttachment (بدون مشاركة نفس file path)
    حتى حذف الـ attachment ما يحذف ملف الـ prescription الأصلي.
    """
    pdf_field = getattr(prescription, "pdf_file", None)
    if not pdf_field:
        return

    try:
        try:
            pdf_field.open("rb")
        except Exception:
            pass
        pdf_bytes = pdf_field.read()
    except Exception as e:
        logger.warning("Cannot read RX PDF for archiving (RX %s): %s", getattr(prescription, "pk", None), e)
        return

    if not pdf_bytes:
        return

    filename = f"rx_{getattr(prescription, 'pk', 'new')}.pdf"

    try:
        att = (
            ArchiveAttachment.objects.filter(archive=archive, description="Prescription PDF")
            .order_by("-id")
            .first()
        )

        if att:
            old_name = getattr(att.file, "name", None)
            att.file.save(filename, ContentFile(pdf_bytes), save=False)

            if _model_has_field(ArchiveAttachment, "uploaded_by") and getattr(user, "is_authenticated", False):
                att.uploaded_by = user

            att.description = "Prescription PDF"
            att.save()

            try:
                new_name = getattr(att.file, "name", None)
                if old_name and new_name and old_name != new_name:
                    try:
                        att.file.storage.delete(old_name)
                    except Exception:
                        pass
            except Exception:
                pass
        else:
            new_att = ArchiveAttachment(
                archive=archive,
                description="Prescription PDF",
            )
            if _model_has_field(ArchiveAttachment, "uploaded_by") and getattr(user, "is_authenticated", False):
                new_att.uploaded_by = user

            new_att.file.save(filename, ContentFile(pdf_bytes), save=False)
            new_att.save()

    except Exception as e:
        logger.warning("Failed attaching/updating PDF copy to archive for RX %s: %s", prescription.pk, e)


def _get_prescription_voice_field(prescription: Prescription):
    """
    يحاول يلقط حقل الصوت من الوصفة بأسماء شائعة أو من الإعدادات.
    """
    for field_name in _possible_voice_field_names():
        if _model_has_field(Prescription, field_name):
            field_obj = getattr(prescription, field_name, None)
            if _filefield_has_content(field_obj):
                return field_obj, field_name

    return None, None


def _upsert_archive_voice_copy(archive: PatientArchive, prescription: Prescription, user) -> None:
    """
    يخزن نسخة من التسجيل الصوتي داخل ArchiveVoiceNote
    بدل ArchiveAttachment لأن الصوت له model مستقل وvalidators خاصة.
    """
    voice_field, voice_field_name = _get_prescription_voice_field(prescription)
    if not voice_field:
        logger.info("RX %s: no stored voice file found on prescription to archive.", getattr(prescription, "pk", None))
        return

    try:
        try:
            voice_field.open("rb")
        except Exception:
            pass
        voice_bytes = voice_field.read()
    except Exception as e:
        logger.warning(
            "Cannot read RX voice file for archiving (RX %s, field %s): %s",
            getattr(prescription, "pk", None),
            voice_field_name,
            e,
        )
        return

    if not voice_bytes:
        logger.warning(
            "RX %s: voice field '%s' exists but returned empty bytes.",
            getattr(prescription, "pk", None),
            voice_field_name,
        )
        return

    original_name = getattr(voice_field, "name", "") or ""
    ext = _guess_audio_extension(filename=original_name)
    filename = f"rx_voice_{getattr(prescription, 'pk', 'new')}{ext}"

    try:
        note = (
            ArchiveVoiceNote.objects.filter(
                archive=archive,
                title="Prescription Voice Note",
            )
            .order_by("-id")
            .first()
        )

        if note:
            old_name = getattr(note.audio, "name", None)
            note.audio.save(filename, ContentFile(voice_bytes), save=False)
            note.title = "Prescription Voice Note"

            if _model_has_field(ArchiveVoiceNote, "recorded_by") and getattr(user, "is_authenticated", False):
                note.recorded_by = user

            note.save()

            try:
                new_name = getattr(note.audio, "name", None)
                if old_name and new_name and old_name != new_name:
                    try:
                        note.audio.storage.delete(old_name)
                    except Exception:
                        pass
            except Exception:
                pass
        else:
            new_note = ArchiveVoiceNote(
                archive=archive,
                title="Prescription Voice Note",
            )

            if _model_has_field(ArchiveVoiceNote, "recorded_by") and getattr(user, "is_authenticated", False):
                new_note.recorded_by = user

            new_note.audio.save(filename, ContentFile(voice_bytes), save=False)
            new_note.save()

    except Exception as e:
        logger.warning(
            "Failed attaching/updating voice copy to archive voice notes for RX %s: %s",
            getattr(prescription, "pk", None),
            e,
        )


def _archive_prescription_if_needed(prescription: Prescription, user, archive_flag: bool) -> None:
    """
    - يربط PatientArchive.prescription = Prescription (إذا الحقل موجود)
    - يربط PatientArchive.appointment (إذا الحقل موجود)
    - يخزن نسخة PDF داخل archive attachments
    - يخزن نسخة Voice Note داخل archive voice notes إذا كانت موجودة
    """
    if not archive_flag:
        return

    patient = getattr(getattr(prescription, "appointment", None), "patient", None) or getattr(prescription, "patient", None)
    doctor = getattr(prescription, "doctor", None)
    appt = getattr(prescription, "appointment", None)

    if not patient or not doctor:
        logger.warning("Cannot archive prescription %s: missing patient or doctor.", getattr(prescription, "pk", None))
        return

    title = f"Prescription #{prescription.pk}"

    has_rx_link = _model_has_field(PatientArchive, "prescription")
    has_appt_link = _model_has_field(PatientArchive, "appointment")

    base_fields: dict = {
        "patient": patient,
        "doctor": doctor,
        "title": title,
    }

    if _model_has_field(PatientArchive, "notes"):
        base_fields["notes"] = getattr(prescription, "instructions", "") or ""
    if _model_has_field(PatientArchive, "archive_type"):
        base_fields["archive_type"] = "prescription"
    if _model_has_field(PatientArchive, "is_critical"):
        base_fields["is_critical"] = False
    if _model_has_field(PatientArchive, "status"):
        base_fields["status"] = "final"
    if _model_has_field(PatientArchive, "created_by") and getattr(user, "is_authenticated", False):
        base_fields["created_by"] = user
    if has_appt_link and appt is not None:
        base_fields["appointment"] = appt
    if has_rx_link:
        base_fields["prescription"] = prescription

    try:
        archive: PatientArchive | None = None
        created = False

        if has_rx_link:
            archive = PatientArchive.objects.filter(prescription=prescription).first()

            if not archive:
                cand_qs = PatientArchive.objects.filter(patient=patient, doctor=doctor, title=title)
                if _model_has_field(PatientArchive, "archive_type"):
                    cand_qs = cand_qs.filter(archive_type="prescription")
                candidate = cand_qs.order_by("-id").first()
                if candidate and not getattr(candidate, "prescription_id", None):
                    archive = candidate

            if not archive:
                archive = PatientArchive.objects.create(**base_fields)
                created = True
            else:
                created = False
        else:
            defaults = base_fields.copy()
            defaults.pop("patient", None)
            defaults.pop("doctor", None)
            defaults.pop("title", None)

            archive, created = PatientArchive.objects.get_or_create(
                patient=patient,
                doctor=doctor,
                title=title,
                defaults=defaults,
            )

        if not archive:
            return

        updated = False

        if has_rx_link and getattr(archive, "prescription_id", None) != prescription.pk:
            try:
                setattr(archive, "prescription", prescription)
                updated = True
            except Exception:
                pass

        if has_appt_link and appt is not None and getattr(archive, "appointment_id", None) != getattr(appt, "pk", None):
            try:
                setattr(archive, "appointment", appt)
                updated = True
            except Exception:
                pass

        if _model_has_field(PatientArchive, "archive_type") and getattr(archive, "archive_type", None) != "prescription":
            try:
                archive.archive_type = "prescription"
                updated = True
            except Exception:
                pass

        if _model_has_field(PatientArchive, "status") and getattr(archive, "status", None) != "final":
            try:
                archive.status = "final"
                updated = True
            except Exception:
                pass

        if _model_has_field(PatientArchive, "notes"):
            ins = getattr(prescription, "instructions", "") or ""
            if ins and (getattr(archive, "notes", "") or "") != ins:
                try:
                    archive.notes = ins
                    updated = True
                except Exception:
                    pass

        if _model_has_field(PatientArchive, "updated_by") and getattr(user, "is_authenticated", False):
            try:
                archive.updated_by = user
                updated = True
            except Exception:
                pass

        if updated and not created:
            archive.save()

        if getattr(prescription, "pdf_file", None):
            _upsert_archive_pdf_copy(archive, prescription, user)

        _upsert_archive_voice_copy(archive, prescription, user)

    except Exception as e:
        logger.exception("Error while archiving prescription %s: %s", getattr(prescription, "pk", None), e)


def _public_download_url(request, token: str) -> Optional[str]:
    """
    يبني رابط تحميل عام آمن (token-gated) إذا عندك route اسمه prescription:public_pdf.
    """
    if not _public_download_enabled():
        return None
    try:
        return request.build_absolute_uri(reverse("prescription:public_pdf", kwargs={"token": token}))
    except NoReverseMatch:
        return None


def _prescription_order_fields() -> list[str]:
    fields: list[str] = []
    if _model_has_field(Prescription, "date_issued"):
        fields.append("-date_issued")
    if _model_has_field(Prescription, "issued_at"):
        fields.append("-issued_at")
    if _model_has_field(Prescription, "created_at"):
        fields.append("-created_at")
    fields.append("-pk")
    return fields


# =========================
# Appointment Status Helper
# =========================
def _mark_appointment_completed(appt: Optional[Appointment]) -> None:
    """
    يخلي appointment.status = 'completed' بأمان.
    - ما يغيّر إذا كان الموعد cancelled.
    - ما يكسر إذا ماكو حقل status.
    """
    if not appt:
        return
    if not hasattr(appt, "status"):
        return

    try:
        current = str(getattr(appt, "status", "") or "").lower()
        if current in {"completed", "cancelled"}:
            return

            # keep state transition narrow
        setattr(appt, "status", "completed")
        appt.save(update_fields=["status"])
    except Exception as e:
        logger.warning("Failed to mark appointment %s as completed: %s", getattr(appt, "pk", None), e)


# =========================
# Create / New RX (Core)
# =========================
@login_required
@require_http_methods(["GET", "POST"])
@cache_control(no_cache=True, no_store=True, must_revalidate=True)
def new_prescription(request) -> HttpResponse:
    return _new_prescription_core(request, forced_appointment_id=None)


@login_required
@require_http_methods(["GET", "POST"])
@cache_control(no_cache=True, no_store=True, must_revalidate=True)
def create_prescription(request, appointment_id: int) -> HttpResponse:
    return _new_prescription_core(request, forced_appointment_id=appointment_id)


@login_required
@require_http_methods(["GET", "POST"])
@cache_control(no_cache=True, no_store=True, must_revalidate=True)
def prescription_create(request, appointment_id: Optional[int] = None) -> HttpResponse:
    return _new_prescription_core(request, forced_appointment_id=appointment_id)


def _new_prescription_core(request, forced_appointment_id: Optional[int] = None) -> HttpResponse:
    user = request.user
    r = _role(user)

    if not (getattr(user, "is_superuser", False) or r == "doctor" or _user_in_group(user, "Doctors")):
        return HttpResponseForbidden("Only doctors can create prescriptions.")

    doctor_obj: Optional[Doctor] = None
    try:
        doctor_obj = Doctor.objects.select_related("user").get(user=user)
    except Doctor.DoesNotExist:
        doctor_obj = None

    appt_qs_all = _appointments_for_user(user)
    appt_qs = _appointments_without_prescriptions(appt_qs_all)

    selected_appt = _pick_selected_appointment(request, appt_qs_all, forced_appointment_id)
    has_explicit_selection = _has_explicit_appointment_selection(request, forced_appointment_id)

    # نحوّل إلى الوصفة الموجودة فقط إذا كان الموعد مختارًا بشكل صريح
    if selected_appt is not None and has_explicit_selection:
        existing = Prescription.objects.filter(appointment=selected_appt).only("pk").first()
        if existing and request.method == "GET":
            messages.info(request, "هذا الموعد عنده وصفة مسبقًا. تم فتح الوصفة الموجودة.")
            return redirect("prescription:prescription_detail", pk=existing.pk)

    next_appointment = _next_appointment_after(_appointments_without_prescriptions(appt_qs_all), selected_appt)
    appointment_id_for_form = selected_appt.pk if selected_appt else None

    if request.method == "POST":
        form = _safe_prescription_form(
            request.POST,
            request.FILES,
            appointment_id=appointment_id_for_form,
            user=user,
        )
        _apply_force_archive_ui(form)

        medication_formset = MedicationFormSet(
            request.POST,
            request.FILES,
            prefix="med",
            instance=Prescription(),
        )

        if "appointment" in getattr(form, "fields", {}):
            form.fields["appointment"].queryset = appt_qs

        if form.is_valid() and medication_formset.is_valid():
            try:
                with transaction.atomic():
                    prescription: Prescription = form.save(commit=False)

                    if getattr(prescription, "appointment_id", None) is None and selected_appt:
                        prescription.appointment = selected_appt

                    if getattr(prescription, "appointment_id", None) and getattr(prescription.appointment, "doctor_id", None):
                        prescription.doctor = prescription.appointment.doctor
                    elif getattr(prescription, "doctor_id", None) is None and doctor_obj:
                        prescription.doctor = doctor_obj

                    user_choice = (
                        bool(form.cleaned_data.get("archive_prescription"))
                        if hasattr(form, "cleaned_data")
                        else False
                    )
                    archive_flag = True if _force_archive_enabled() else user_choice

                    if archive_flag and hasattr(prescription, "status"):
                        prescription.status = "completed"

                    prescription.save()

                    if hasattr(form, "save_m2m"):
                        try:
                            form.save_m2m()
                        except Exception:
                            pass

                    _persist_request_voice_to_prescription(
                        request=request,
                        prescription=prescription,
                        form=form,
                    )

                    medication_formset.instance = prescription
                    medication_formset.save()

                    _ensure_assets_after_medications(prescription, force_pdf=True)

                    _schedule_archive_after_commit(
                        prescription_id=prescription.pk,
                        user=user,
                        archive_flag=archive_flag,
                    )

                    _mark_appointment_completed(getattr(prescription, "appointment", None))

                messages.success(request, "✅ تم إنشاء الوصفة بنجاح.")
                return redirect("prescription:prescription_detail", pk=prescription.pk)

            except IntegrityError:
                form.add_error("appointment", "A prescription already exists for this appointment.")
            except Exception as e:
                logger.exception("Prescription create failed: %s", e)
                messages.error(request, "❌ صار خطأ أثناء إنشاء الوصفة.")

        else:
            messages.error(request, "⚠️ يرجى تصحيح الأخطاء في الحقول.")

    else:
        form = _safe_prescription_form(appointment_id=appointment_id_for_form, user=user)
        _apply_force_archive_ui(form)

        medication_formset = MedicationFormSet(prefix="med", instance=Prescription())
        if "appointment" in getattr(form, "fields", {}):
            form.fields["appointment"].queryset = appt_qs

    context = {
        "form": form,
        "medication_formset": medication_formset,
        "editing": False,
        "selected_appointment": selected_appt,
        "next_appointment": next_appointment,
        "has_appointments": appt_qs.exists(),
        "force_archive": _force_archive_enabled(),
    }
    return render(request, "prescription/prescription_create.html", context)


# =========================
# Edit / Update RX
# =========================
@login_required
@require_http_methods(["GET", "POST"])
@cache_control(no_cache=True, no_store=True, must_revalidate=True)
def _edit_prescription_core(request, pk: int) -> HttpResponse:
    prescription = get_object_or_404(
        Prescription.objects.select_related("doctor__user", "appointment__patient__user"),
        pk=pk,
    )

    if not _can_manage_prescription(request.user, prescription):
        return HttpResponseForbidden("You are not allowed to edit this prescription.")

    user = request.user
    r = _role(user)

    if getattr(user, "is_superuser", False) or (r in {"admin"} and _admin_can_access_prescriptions()) or (
        r == "secretary" and _secretary_can_access_prescriptions()
    ):
        appt_qs_all = Appointment.objects.select_related("patient__user", "doctor__user").all()
    else:
        appt_qs_all = Appointment.objects.select_related("patient__user", "doctor__user").filter(doctor__user=user)

    appt_qs_all = appt_qs_all.order_by("scheduled_time", "pk")

    free_qs = _appointments_without_prescriptions(appt_qs_all)
    appt_qs = (free_qs | appt_qs_all.filter(pk=prescription.appointment_id)).order_by("scheduled_time", "pk")

    next_appointment = _next_appointment_after(_appointments_without_prescriptions(appt_qs_all), prescription.appointment)
    appointment_id_for_form = prescription.appointment_id

    if request.method == "POST":
        form = _safe_prescription_form(
            request.POST,
            request.FILES,
            instance=prescription,
            appointment_id=appointment_id_for_form,
            user=user,
        )
        _apply_force_archive_ui(form)

        medication_formset = MedicationFormSet(
            request.POST,
            request.FILES,
            prefix="med",
            instance=prescription,
        )

        if "appointment" in getattr(form, "fields", {}):
            form.fields["appointment"].queryset = appt_qs

        if form.is_valid() and medication_formset.is_valid():
            try:
                with transaction.atomic():
                    prescription = form.save(commit=False)

                    if getattr(prescription, "appointment_id", None) and getattr(prescription, "appointment", None):
                        if prescription.appointment.doctor_id != prescription.doctor_id:
                            prescription.doctor = prescription.appointment.doctor

                    user_choice = (
                        bool(form.cleaned_data.get("archive_prescription"))
                        if hasattr(form, "cleaned_data")
                        else False
                    )
                    archive_flag = True if _force_archive_enabled() else user_choice

                    if archive_flag and hasattr(prescription, "status"):
                        prescription.status = "completed"

                    prescription.save()

                    if hasattr(form, "save_m2m"):
                        try:
                            form.save_m2m()
                        except Exception:
                            pass

                    _persist_request_voice_to_prescription(
                        request=request,
                        prescription=prescription,
                        form=form,
                    )

                    medication_formset.save()

                    _ensure_assets_after_medications(prescription, force_pdf=True)

                    _schedule_archive_after_commit(
                        prescription_id=prescription.pk,
                        user=user,
                        archive_flag=archive_flag,
                    )

                    _mark_appointment_completed(getattr(prescription, "appointment", None))

                messages.success(request, "✅ تم تحديث الوصفة بنجاح.")
                return redirect("prescription:prescription_detail", pk=prescription.pk)

            except IntegrityError:
                form.add_error("appointment", "A prescription already exists for this appointment.")
            except Exception as e:
                logger.exception("Prescription update failed: %s", e)
                messages.error(request, "❌ صار خطأ أثناء تحديث الوصفة.")

        else:
            messages.error(request, "⚠️ يرجى تصحيح الأخطاء في الحقول.")

    else:
        form = _safe_prescription_form(instance=prescription, appointment_id=appointment_id_for_form, user=user)
        _apply_force_archive_ui(form)

        medication_formset = MedicationFormSet(prefix="med", instance=prescription)

        if "appointment" in getattr(form, "fields", {}):
            form.fields["appointment"].queryset = appt_qs

    context = {
        "form": form,
        "medication_formset": medication_formset,
        "editing": True,
        "selected_appointment": prescription.appointment,
        "next_appointment": next_appointment,
        "has_appointments": appt_qs.exists(),
        "prescription": prescription,
        "force_archive": _force_archive_enabled(),
    }
    return render(request, "prescription/prescription_create.html", context)


def edit_prescription(request, pk: int) -> HttpResponse:
    return _edit_prescription_core(request, pk)


def prescription_edit(request, pk: int) -> HttpResponse:
    return _edit_prescription_core(request, pk)


def update_prescription(request, pk: int) -> HttpResponse:
    return _edit_prescription_core(request, pk)


# =========================
# Delete RX
# =========================
@login_required
@require_http_methods(["GET", "POST"])
@cache_control(no_cache=True, no_store=True, must_revalidate=True)
def _delete_prescription_core(request, pk: int) -> HttpResponse:
    p = get_object_or_404(
        Prescription.objects.select_related("doctor__user", "appointment__patient__user"),
        pk=pk,
    )

    if not _can_manage_prescription(request.user, p):
        return HttpResponseForbidden("You are not allowed to delete this prescription.")

    if request.method == "POST":
        p.delete()
        messages.success(request, "✅ تم حذف الوصفة بنجاح.")
        return redirect("prescription:list")

    return render(request, "prescription/prescription_delete_confirmation.html", {"p": p})


def delete_prescription(request, pk: int) -> HttpResponse:
    return _delete_prescription_core(request, pk)


def prescription_delete(request, pk: int) -> HttpResponse:
    return _delete_prescription_core(request, pk)


def remove_prescription(request, pk: int) -> HttpResponse:
    return _delete_prescription_core(request, pk)


# =========================
# List (module index)
# =========================
@require_GET
@login_required
@cache_control(no_cache=True, no_store=True, must_revalidate=True)
def prescription_list(request) -> HttpResponse:
    user = request.user
    r = _role(user)

    qs = Prescription.objects.select_related("doctor__user", "appointment__patient__user")

    if getattr(user, "is_superuser", False):
        pass
    elif r == "admin":
        if not _admin_can_access_prescriptions():
            return HttpResponseForbidden("You do not have access to prescriptions.")
    elif r == "secretary":
        if not _secretary_can_access_prescriptions():
            return HttpResponseForbidden("You do not have access to prescriptions.")
    elif r == "doctor" or _user_in_group(user, "Doctors"):
        qs = qs.filter(doctor__user=user)
    elif r == "patient" or _user_in_group(user, "Patients"):
        qs = qs.filter(appointment__patient__user=user)
    else:
        return HttpResponseForbidden("You do not have access to prescriptions.")

    qs = qs.order_by(*_prescription_order_fields())
    return render(request, "prescription/prescription_list.html", {"prescriptions": qs})


index = prescription_list
prescriptions = prescription_list
list_prescriptions = prescription_list


# =========================
# Private
# =========================
@require_GET
@login_required
@cache_control(no_cache=True, no_store=True, must_revalidate=True)
def prescription_detail(request, pk: int) -> HttpResponse:
    p = get_object_or_404(
        Prescription.objects.select_related("doctor__user", "appointment__patient__user"),
        pk=pk,
    )
    if not _can_view_prescription(request.user, p):
        return HttpResponseForbidden("You do not have access to this prescription.")

    verify_url = _build_verify_url(request, p)
    qr_code_b64 = _qr_b64_from_url(verify_url) if verify_url else None

    whatsapp_share_url: Optional[str] = None
    if verify_url:
        text = f"ClinicHub prescription verification link: {verify_url}"
        whatsapp_share_url = f"https://wa.me/?text={quote(text)}"

    context = {
        "p": p,
        "verify_url": verify_url,
        "qr_code_b64": qr_code_b64,
        "qr_svg_uri": None,
        "whatsapp_share_url": whatsapp_share_url,
    }
    return render(request, "prescription/prescription_detail.html", context)


def detail(request, pk: int) -> HttpResponse:
    return prescription_detail(request, pk)


def show_prescription(request, pk: int) -> HttpResponse:
    return prescription_detail(request, pk)


# =========================
# PDF (Private Download)
# =========================
@require_GET
@login_required
@cache_control(no_cache=True, no_store=True, must_revalidate=True)
def download_pdf_prescription(request, pk: int) -> FileResponse:
    p = get_object_or_404(
        Prescription.objects.select_related("doctor__user", "appointment__patient__user"),
        pk=pk,
    )
    if not _can_view_prescription(request.user, p):
        return HttpResponseForbidden("You do not have access to this prescription.")

    if not getattr(p, "pdf_file", None):
        try:
            if hasattr(p, "medications") and p.medications.exists():
                _ensure_assets_after_medications(p, force_pdf=True)
        except Exception as e:
            logger.warning("PDF generation failed for RX %s: %s", p.pk, e)

    if not getattr(p, "pdf_file", None):
        raise Http404("PDF not found.")

    resp = FileResponse(p.pdf_file.open("rb"), content_type="application/pdf")
    resp["Content-Disposition"] = f'attachment; filename="ClinicHub_Prescription_{p.pk:06d}.pdf"'
    return resp


@require_GET
@login_required
@cache_control(no_cache=True, no_store=True, must_revalidate=True)
def prescription_pdf(request, pk: int) -> FileResponse:
    p = get_object_or_404(
        Prescription.objects.select_related("doctor__user", "appointment__patient__user"),
        pk=pk,
    )
    if not _can_view_prescription(request.user, p):
        return HttpResponseForbidden("You do not have access to this prescription.")

    if not getattr(p, "pdf_file", None):
        try:
            if hasattr(p, "medications") and p.medications.exists():
                _ensure_assets_after_medications(p, force_pdf=True)
        except Exception:
            pass

    if not getattr(p, "pdf_file", None):
        raise Http404("PDF not found.")

    resp = FileResponse(p.pdf_file.open("rb"), content_type="application/pdf")
    resp["Content-Disposition"] = f'inline; filename="rx_{p.pk}.pdf"'
    return resp


def pdf(request, pk: int) -> FileResponse:
    return prescription_pdf(request, pk)


# =========================
# WhatsApp (Private)
# =========================
@require_GET
@login_required
@cache_control(no_cache=True, no_store=True, must_revalidate=True)
def send_prescription_whatsapp(request, pk: int) -> HttpResponse:
    p = get_object_or_404(
        Prescription.objects.select_related("doctor__user", "appointment__patient__user"),
        pk=pk,
    )
    if not _can_view_prescription(request.user, p):
        return HttpResponseForbidden("You do not have access to this prescription.")

    verify_url = _build_verify_url(request, p)
    fallback_url = request.build_absolute_uri(reverse("prescription:prescription_detail", kwargs={"pk": p.pk}))
    url = verify_url or fallback_url

    text = f"ClinicHub prescription link: {url}"
    wa = f"https://wa.me/?text={quote(text)}"
    return redirect(wa)


def prescription_whatsapp(request, pk: int) -> HttpResponse:
    return send_prescription_whatsapp(request, pk)


def send_whatsapp(request, pk: int) -> HttpResponse:
    return send_prescription_whatsapp(request, pk)


# =========================
# Public
# =========================
@require_GET
@cache_control(no_cache=True, no_store=True, must_revalidate=True)
def verify(request, token: str) -> HttpResponse:
    """
    Public verification (بدون تسجيل دخول) — PHI-FREE.
    يثبت صحة الوصفة دون عرض اسم المريض أو بيانات حساسة.
    """
    salts_to_try = ["rx.verify", "prescription.verify"]

    data = None
    last_error: Optional[Exception] = None

    for s in salts_to_try:
        try:
            data = loads(token, salt=s, max_age=_verify_max_age_seconds())
            if isinstance(data, dict) and "pid" in data:
                break
        except (BadSignature, SignatureExpired, ValueError, TypeError) as e:
            last_error = e
            data = None

    if not data:
        logger.info("RX verify failed: %s", last_error)
        ctx = {
            "valid": False,
            "is_valid": False,
            "reason": "Invalid or expired token.",
            "error": "Invalid or expired token.",
            "rx_id": None,
            "doctor": None,
            "issued_at": None,
            "status": None,
            "download_url": None,
            "checksum": _token_fingerprint(token),
            "token": token,
        }
        return render(request, "prescription/verify.html", ctx, status=400)

    try:
        pid = int(data.get("pid"))
    except (ValueError, TypeError):
        ctx = {
            "valid": False,
            "is_valid": False,
            "reason": "Invalid token payload.",
            "error": "Invalid token payload.",
            "rx_id": None,
            "doctor": None,
            "issued_at": None,
            "status": None,
            "download_url": None,
            "checksum": _token_fingerprint(token),
            "token": token,
        }
        return render(request, "prescription/verify.html", ctx, status=400)

    p = Prescription.objects.select_related("doctor__user").filter(pk=pid).first()
    if not p:
        ctx = {
            "valid": False,
            "is_valid": False,
            "reason": "Prescription not found.",
            "error": "Prescription not found.",
            "rx_id": pid,
            "doctor": None,
            "issued_at": None,
            "status": None,
            "download_url": None,
            "checksum": _token_fingerprint(token),
            "token": token,
        }
        return render(request, "prescription/verify.html", ctx, status=404)

    doctor_name = (
        getattr(p, "doctor_display_name", None)
        or (p.doctor.user.get_full_name() if getattr(p.doctor, "user", None) else None)
        or "Doctor"
    )

    ctx = {
        "valid": True,
        "is_valid": True,
        "reason": None,
        "error": None,
        "rx_id": p.pk,
        "doctor": doctor_name,
        "issued_at": _issued_display(p),
        "status": getattr(p, "status", "draft"),
        "download_url": _public_download_url(request, token),
        "checksum": _token_fingerprint(token),
        "prescription": p if getattr(settings, "PRESCRIPTION_VERIFY_EXPOSE_OBJECT", False) else None,
        "token": token,
    }
    return render(request, "prescription/verify.html", ctx)


@require_GET
@cache_control(no_cache=True, no_store=True, must_revalidate=True)
def public_pdf(request, token: str) -> FileResponse:
    """
    Public PDF download via token (اختياري).
    لازم تفعّلين: PRESCRIPTION_PUBLIC_DOWNLOAD=True
    ولازم تضيفين route اسمه prescription:public_pdf في urls.py
    """
    if not _public_download_enabled():
        raise Http404()

    salts_to_try = ["rx.verify", "prescription.verify"]
    data = None
    for s in salts_to_try:
        try:
            data = loads(token, salt=s, max_age=_verify_max_age_seconds())
            if isinstance(data, dict) and "pid" in data:
                break
        except Exception:
            data = None

    if not data:
        raise Http404()

    try:
        pid = int(data.get("pid"))
    except Exception:
        raise Http404()

    p = Prescription.objects.select_related("doctor__user").filter(pk=pid).first()
    if not p:
        raise Http404()

    if not getattr(p, "pdf_file", None):
        try:
            if hasattr(p, "medications") and p.medications.exists():
                _ensure_assets_after_medications(p, force_pdf=True)
        except Exception:
            pass

    if not getattr(p, "pdf_file", None):
        raise Http404("PDF not found.")

    resp = FileResponse(p.pdf_file.open("rb"), content_type="application/pdf")
    resp["Content-Disposition"] = f'attachment; filename="ClinicHub_Prescription_{p.pk:06d}.pdf"'
    return resp


public_verify = verify