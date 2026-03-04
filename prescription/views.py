# prescription/views.py
from __future__ import annotations

import base64
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
from medical_archive.models import ArchiveAttachment, PatientArchive

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
    افتراضياً: السكرتيرة ما تشوف الوصفات (حسب تفضيلك السابق).
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
    ✅ الأرشفة الآلية 100% (بدون الاعتماد على checkbox)
    الافتراضي True حتى يطابق نصّ Phase 3 (automatic PDF archiving).
    لإيقافها: PRESCRIPTION_FORCE_ARCHIVE = False
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

    # optional access (ONLY if enabled)
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
    edit/delete: نفس view (أكثر تحفظاً).
    """
    if getattr(user, "is_superuser", False):
        return True

    r = _role(user)

    # optional manage (ONLY if enabled)
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
    ✅ إذا الأرشفة إجبارية: نخلي checkbox ثابت (disabled) حتى ما يصير لخبطة للمستخدم.
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
    ✅ آمن بدون الاعتماد على reverse relation name.
    """
    try:
        used_ids = Prescription.objects.exclude(appointment_id__isnull=True).values_list("appointment_id", flat=True)
        return appt_qs.exclude(id__in=used_ids)
    except Exception:
        return appt_qs


def _pick_selected_appointment(request, appt_qs, forced_appointment_id: Optional[int]) -> Optional[Appointment]:
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

    today = timezone.localdate()
    return appt_qs.filter(scheduled_time__date=today).first()


def _next_appointment_after(appt_qs, selected: Optional[Appointment]) -> Optional[Appointment]:
    if not selected or not getattr(selected, "scheduled_time", None):
        return None
    return appt_qs.filter(scheduled_time__gt=selected.scheduled_time).first()


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

    # cleanup old files (best-effort)
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
    ✅ IMPORTANT FIX:
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

            # Best-effort: delete old stored file if it changed
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


def _archive_prescription_if_needed(prescription: Prescription, user, archive_flag: bool) -> None:
    """
    ✅ FIXED:
    - يربط PatientArchive.prescription = Prescription (إذا الحقل موجود)
    - يربط PatientArchive.appointment (إذا الحقل موجود)
    - يخزن نسخة PDF داخل archive attachments (بدون مشاركة نفس الملف)
    """
    if not archive_flag:
        return

    patient = getattr(getattr(prescription, "appointment", None), "patient", None) or getattr(prescription, "patient", None)
    doctor = getattr(prescription, "doctor", None)
    appt = getattr(prescription, "appointment", None)

    if not patient or not doctor:
        logger.warning("Cannot archive prescription %s: missing patient or doctor.", prescription.pk)
        return

    title = f"Prescription #{prescription.pk}"

    has_rx_link = _model_has_field(PatientArchive, "prescription")
    has_appt_link = _model_has_field(PatientArchive, "appointment")

    # ---------- Build create/default fields ----------
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
            # 1) Prefer strict link by prescription (OneToOne)
            archive = PatientArchive.objects.filter(prescription=prescription).first()

            # 2) If not found, try to reuse an older record by patient/doctor/title (if it has no prescription)
            if not archive:
                cand_qs = PatientArchive.objects.filter(patient=patient, doctor=doctor, title=title)
                if _model_has_field(PatientArchive, "archive_type"):
                    cand_qs = cand_qs.filter(archive_type="prescription")
                candidate = cand_qs.order_by("-id").first()
                if candidate and not getattr(candidate, "prescription_id", None):
                    archive = candidate

            # 3) If still not found, create
            if not archive:
                archive = PatientArchive.objects.create(**base_fields)
                created = True
            else:
                created = False
        else:
            # Fallback build (بدون حقل prescription)
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

        # ---------- Update existing archive to ensure consistency ----------
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

        # ---------- Attach PDF as a COPY inside archive ----------
        if getattr(prescription, "pdf_file", None):
            _upsert_archive_pdf_copy(archive, prescription, user)

    except Exception as e:
        logger.error("Error while archiving prescription %s: %s", prescription.pk, e)


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
# ✅ Appointment Status Helper
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

        setattr(appt, "status", "completed")
        appt.save(update_fields=["status"])
    except Exception as e:
        logger.warning("Failed to mark appointment %s as completed: %s", getattr(appt, "pk", None), e)


# =========================
#   Create / New RX (Core)
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

    # doctor profile (اختياري للسوبر يوزر)
    doctor_obj: Optional[Doctor] = None
    try:
        doctor_obj = Doctor.objects.select_related("user").get(user=user)
    except Doctor.DoesNotExist:
        doctor_obj = None

    appt_qs_all = _appointments_for_user(user)

    # ✅ فقط المواعيد اللي ما عليها وصفة (آمن)
    appt_qs = _appointments_without_prescriptions(appt_qs_all)

    selected_appt = _pick_selected_appointment(request, appt_qs_all, forced_appointment_id)

    # إذا الموعد المختار عليه وصفة موجودة، حوّل لصفحة التفاصيل بدل إنشاء جديد
    if selected_appt is not None:
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

                    # ensure appointment/doctor set
                    if getattr(prescription, "appointment_id", None) is None and selected_appt:
                        prescription.appointment = selected_appt

                    # doctor always from appointment preferred
                    if getattr(prescription, "appointment_id", None) and getattr(prescription.appointment, "doctor_id", None):
                        prescription.doctor = prescription.appointment.doctor
                    elif getattr(prescription, "doctor_id", None) is None and doctor_obj:
                        prescription.doctor = doctor_obj

                    # ✅ ARCHIVING POLICY:
                    # - إذا PRESCRIPTION_FORCE_ARCHIVE=True => دائما True
                    # - غير ذلك => يعتمد على checkbox
                    user_choice = (
                        bool(form.cleaned_data.get("archive_prescription"))
                        if hasattr(form, "cleaned_data")
                        else False
                    )
                    archive_flag = True if _force_archive_enabled() else user_choice

                    # لو عندك status بالحقل نعتبرها completed عند الأرشفة
                    if archive_flag and hasattr(prescription, "status"):
                        prescription.status = "completed"

                    prescription.save()

                    medication_formset.instance = prescription
                    medication_formset.save()

                    # ✅ ensure PDF/QR first, then archive attaches PDF
                    _ensure_assets_after_medications(prescription, force_pdf=True)

                    _archive_prescription_if_needed(
                        prescription=prescription,
                        user=user,
                        archive_flag=archive_flag,
                    )

                    # ✅ IMPORTANT: mark appointment completed after successful RX save
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
#   Edit / Update RX
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
    appt_qs = free_qs | appt_qs_all.filter(pk=prescription.appointment_id)

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

                    # keep doctor aligned with appointment
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
                    medication_formset.save()

                    _ensure_assets_after_medications(prescription, force_pdf=True)

                    _archive_prescription_if_needed(
                        prescription=prescription,
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
#   Delete RX
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
#      List (module index)
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
#         Private
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
#     PDF (Private Download)
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
#      WhatsApp (Private)
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
#          Public
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