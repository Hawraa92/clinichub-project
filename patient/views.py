# patient/views.py
from __future__ import annotations

import json
from datetime import date, timedelta
from typing import Any, Final, Optional

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required, user_passes_test
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.db import IntegrityError
from django.db.models import Count, Q
from django.db.models.functions import Lower, TruncDate
from django.shortcuts import get_object_or_404, redirect, render
from django.template import TemplateDoesNotExist
from django.utils import timezone
from django.utils.translation import gettext as _
from django.views.decorators.http import require_http_methods

from appointments.models import Appointment
from patient.forms import DoctorPatientForm, SecretaryPatientForm
from patient.models import DiabetesStatus, Patient
from prescription.models import Prescription

try:
    from billing.models import Invoice  # type: ignore
    HAS_BILLING = True
except Exception:
    Invoice = None  # type: ignore
    HAS_BILLING = False


# -----------------------------
# Settings / constants
# -----------------------------
PAGE_SIZE: Final[int] = getattr(settings, "PATIENT_LIST_PAGE_SIZE", 25)

# ✅ إذا السكرتير ما عنده assigned doctor:
# True  -> يشوف كل المرضى/Recycle Bin
# False -> يظل لازم يكون مرتبط بطبيب
SECRETARY_SEES_ALL_PATIENTS: Final[bool] = bool(getattr(settings, "SECRETARY_SEES_ALL_PATIENTS", True))


GROUPS_MAP = {
    "doctor": "Doctors",
    "secretary": "Secretaries",
}


# -----------------------------
# Role helpers
# -----------------------------
def _has_role(user, role_name: str) -> bool:
    group_name = GROUPS_MAP.get(role_name)
    try:
        in_group = bool(group_name) and user.groups.filter(name=group_name).exists()
    except Exception:
        in_group = False
    return getattr(user, "role", "") == role_name or in_group


def is_doctor(user) -> bool:  # noqa: ANN001
    return _has_role(user, "doctor")


def is_secretary(user) -> bool:  # noqa: ANN001
    return _has_role(user, "secretary")


def is_patient(user) -> bool:  # noqa: ANN001
    return hasattr(user, "patient_profile") or hasattr(user, "patient")


def is_med_staff(user) -> bool:  # noqa: ANN001
    return is_doctor(user) or is_secretary(user)


# ✅ Keep decorators (but we’ll avoid raising 403 inside views)
doctor_required = user_passes_test(is_doctor)
secretary_required = user_passes_test(is_secretary)
med_staff_required = user_passes_test(is_med_staff)
patient_required = user_passes_test(is_patient)


def _model_has_field(model_cls: type, name: str) -> bool:
    try:
        model_cls._meta.get_field(name)
        return True
    except Exception:
        return False


def _prediction_field_name() -> str:
    """
    Prefer diabetes_prediction (AI output) for listing/filtering.
    Fallback to diabetes_status.
    """
    if _model_has_field(Patient, "diabetes_prediction"):
        return "diabetes_prediction"
    if _model_has_field(Patient, "diabetes_status"):
        return "diabetes_status"
    # بدل 403: نرجع اسم افتراضي حتى ما يوقف النظام
    return "diabetes_status"


# -----------------------------
# Doctor assignment helpers
# -----------------------------
def _current_doctor_for(user) -> Optional["doctor.Doctor"]:  # type: ignore[name-defined]
    try:
        from doctor.models import Doctor
        qs = Doctor.objects.select_related("user").filter(user=user)

        if hasattr(Doctor, "available"):
            qs = qs.filter(available=True)
        elif hasattr(Doctor, "is_available"):
            qs = qs.filter(is_available=True)

        return qs.first()
    except Exception:
        return None


def _doctor_for_secretary(user) -> Optional["doctor.Doctor"]:  # type: ignore[name-defined]
    try:
        from doctor.models import Doctor
    except Exception:
        return None

    direct = getattr(user, "assigned_doctor", None)
    if isinstance(direct, Doctor):
        return direct

    direct_id = getattr(user, "assigned_doctor_id", None)
    if direct_id:
        return Doctor.objects.select_related("user").filter(pk=direct_id).first()

    alt = getattr(user, "primary_doctor", None) or getattr(user, "doctor", None)
    if isinstance(alt, Doctor):
        return alt

    alt_id = getattr(user, "primary_doctor_id", None) or getattr(user, "doctor_id", None)
    if alt_id:
        return Doctor.objects.select_related("user").filter(pk=alt_id).first()

    for attr in ("secretary_profile", "secretary", "profile", "staff_profile"):
        obj = getattr(user, attr, None)
        if obj is None:
            continue
        doc = getattr(obj, "doctor", None) or getattr(obj, "assigned_doctor", None)
        if isinstance(doc, Doctor):
            return doc

    return None


def _assigned_doctor_for(user) -> Optional["doctor.Doctor"]:  # type: ignore[name-defined]
    if is_doctor(user):
        return _current_doctor_for(user)
    if is_secretary(user):
        return _doctor_for_secretary(user)
    return None


def _forbidden_redirect(request, msg: str):
    """
    بدل 403: رسالة + Redirect
    """
    messages.error(request, msg)
    # تقدرين تغيّرينها لصفحة dashboard إذا عندك
    return redirect("home:index")


def _patients_qs_for(request):
    """
    ACTIVE patients only (Patient.objects may already filter is_deleted=False).
    Doctor: scoped to his patients.
    Secretary:
      - إذا عنده assigned doctor -> scoped
      - إذا ما عنده و SECRETARY_SEES_ALL_PATIENTS=True -> يشوف الكل
    """
    if not is_med_staff(request.user):
        raise PermissionDenied

    if is_doctor(request.user):
        doc = _assigned_doctor_for(request.user)
        if not doc:
            raise PermissionDenied(_("No doctor profile found for your account."))
        return Patient.objects.select_related("doctor", "doctor__user").filter(doctor=doc)

    # secretary
    doc = _assigned_doctor_for(request.user)
    base = Patient.objects.select_related("doctor", "doctor__user")
    if doc:
        return base.filter(doctor=doc)

    if SECRETARY_SEES_ALL_PATIENTS:
        return base

    raise PermissionDenied(_("No assigned doctor found for your account."))


def _patients_deleted_qs_for(request):
    """
    Deleted patients (Recycle Bin), scoped similarly.
    Requires Patient.deleted_objects.
    """
    if not is_med_staff(request.user):
        raise PermissionDenied

    if not hasattr(Patient, "deleted_objects"):
        raise PermissionDenied(_("Recycle Bin is not enabled for Patient model."))

    if is_doctor(request.user):
        doc = _assigned_doctor_for(request.user)
        if not doc:
            raise PermissionDenied(_("No doctor profile found for your account."))
        return Patient.deleted_objects.select_related("doctor", "doctor__user").filter(doctor=doc)

    # secretary
    doc = _assigned_doctor_for(request.user)
    base = Patient.deleted_objects.select_related("doctor", "doctor__user")
    if doc:
        return base.filter(doctor=doc)

    if SECRETARY_SEES_ALL_PATIENTS:
        return base

    raise PermissionDenied(_("No assigned doctor found for your account."))


# -------------------------------------------------------------------
# AI / Prediction helpers (robust)
# -------------------------------------------------------------------
def _to_int_or_none(v: Any) -> Optional[int]:
    if v is None:
        return None
    try:
        return int(v)
    except Exception:
        try:
            return int(getattr(v, "value"))
        except Exception:
            return None


def _safe_float(v: Any) -> Optional[float]:
    try:
        return float(v)
    except Exception:
        return None


def _get_prediction_proba_dict(patient: Patient) -> dict[str, float]:
    candidates = (
        "prediction_proba",
        "diabetes_prediction_proba",
        "diabetes_proba",
        "proba",
    )

    raw: Any = None
    for name in candidates:
        raw = getattr(patient, name, None)
        if raw not in (None, "", {}, []):
            break

    if raw in (None, "", {}, []):
        return {}

    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except Exception:
            return {}

    if not isinstance(raw, dict):
        return {}

    out: dict[str, float] = {}
    for k, v in raw.items():
        fv = _safe_float(v)
        if fv is None:
            continue
        out[str(k)] = fv
    return out


def _resolve_predicted_class_key(patient: Patient, proba: dict[str, float]) -> Optional[str]:
    pred_val = getattr(patient, "diabetes_prediction", None)
    if pred_val is None:
        pred_val = getattr(patient, "diabetes_status", None)

    pred_int = _to_int_or_none(pred_val)
    if pred_int is not None:
        key = str(pred_int)
        if key in proba:
            return key

    if not proba:
        return None
    try:
        return max(proba.keys(), key=lambda kk: float(proba.get(kk, 0.0)))
    except Exception:
        return None


def _compute_confidence_percent(patient: Patient) -> tuple[Optional[float], Optional[float]]:
    proba = _get_prediction_proba_dict(patient)
    if not proba:
        return None, None

    target_key = _resolve_predicted_class_key(patient, proba)
    if not target_key or target_key not in proba:
        return None, None

    p = _safe_float(proba.get(target_key))
    if p is None:
        return None, None

    p = max(0.0, min(1.0, p))
    confidence_pct = round(p * 100.0, 1)
    confidence_angle = round((confidence_pct / 100.0) * 180.0, 1)
    return confidence_pct, confidence_angle


def _should_run_ai_on_save(request) -> bool:
    """
    default: DO NOT run AI on create/edit
    enable via settings.RUN_AI_ON_PATIENT_SAVE = True
    """
    return bool(getattr(settings, "RUN_AI_ON_PATIENT_SAVE", False)) and is_doctor(request.user)


# -------------------------------------------------------------------
# Views
# -------------------------------------------------------------------
@login_required
@med_staff_required
@require_http_methods(["GET", "POST"])
def create_patient(request):
    """
    ✅ Fix for Render 403:
    - إذا السكرتير ما عنده assigned doctor: ما نرفع PermissionDenied
      بل نخلي الفورم يعتمد على حقل doctor إذا موجود، وإلا نرجّع redirect برسالة.
    """
    FormClass = DoctorPatientForm if is_doctor(request.user) else SecretaryPatientForm

    assigned_doc = _assigned_doctor_for(request.user)

    # initial doctor فقط إذا متوفر
    initial = {}
    if assigned_doc:
        initial["doctor"] = assigned_doc

    form = FormClass(request.POST or None, initial=initial)

    if request.method == "POST":
        if form.is_valid():
            patient: Patient = form.save(commit=False)

            # doctor assignment logic
            if is_doctor(request.user):
                if not assigned_doc:
                    return _forbidden_redirect(request, _("No doctor profile found for your account."))
                patient.doctor = assigned_doc

            else:
                # secretary
                if assigned_doc:
                    patient.doctor = assigned_doc
                else:
                    # إذا السكرتير مو مرتبط بطبيب: لازم الطبيب ينأخذ من الفورم إذا موجود
                    if hasattr(form, "cleaned_data") and "doctor" in form.cleaned_data and form.cleaned_data.get("doctor"):
                        patient.doctor = form.cleaned_data["doctor"]
                    else:
                        return _forbidden_redirect(
                            request,
                            _("Your account is not linked to a doctor. Please assign a doctor to the secretary user or enable doctor selection in the form."),
                        )

            patient.save()

            # Optional AI on save
            if _should_run_ai_on_save(request):
                try:
                    from patient.services import predict_and_save
                    predict_and_save(patient)
                    patient.refresh_from_db()
                except Exception:
                    messages.warning(request, _("Patient saved, but AI prediction could not run right now."))

            messages.success(request, _("Patient created successfully."))
            if is_secretary(request.user):
                return redirect("patient:list")
            return redirect("patient:detail", pk=patient.pk)

        messages.error(request, _("Please correct the errors below."))

    return render(request, "patient/create_patient.html", {"form": form})


@login_required
@med_staff_required
@require_http_methods(["GET"])
def patient_list(request):
    try:
        qs = _patients_qs_for(request)
    except PermissionDenied:
        return _forbidden_redirect(request, _("You do not have permission to view patients."))

    search_query = (request.GET.get("q") or "").strip()
    statuses = request.GET.getlist("status")
    sexes = request.GET.getlist("sex")
    sort_key = request.GET.get("sort", "recent")

    if search_query:
        qs = qs.filter(
            Q(full_name__icontains=search_query)
            | Q(mobile__icontains=search_query)
            | Q(email__icontains=search_query)
        )

    pred_field = _prediction_field_name()

    allowed_status = {int(code) for code, _ in DiabetesStatus.choices}
    statuses_int: list[int] = []
    for s in statuses:
        try:
            v = int(s)
        except ValueError:
            continue
        if v in allowed_status:
            statuses_int.append(v)

    if statuses_int:
        qs = qs.filter(**{f"{pred_field}__in": statuses_int})

    try:
        sex_choices = Patient._meta.get_field("sex").choices
        allowed_sex = {choice[0] for choice in sex_choices} if sex_choices else set()
    except Exception:
        allowed_sex = set()

    sexes = [s for s in sexes if s in allowed_sex]
    if sexes:
        qs = qs.filter(sex__in=sexes)

    sort_map = {
        "name_asc": Lower("full_name").asc(),
        "name_desc": Lower("full_name").desc(),
        "status": pred_field,
        "recent": "-created_at",
    }
    order_by = sort_map.get(sort_key, "-created_at")
    qs = qs.order_by(order_by)

    diabetic_count = qs.filter(**{pred_field: int(DiabetesStatus.DIABETIC)}).count()
    new_this_week = qs.filter(created_at__gte=timezone.now() - timedelta(days=7)).count()

    paginator = Paginator(qs, PAGE_SIZE)
    patients_page = paginator.get_page(request.GET.get("page"))

    context = {
        "patients": patients_page,
        "diabetic_count": diabetic_count,
        "new_this_week": new_this_week,
        "search_query": search_query,
        "selected_statuses": [str(s) for s in statuses_int],
        "selected_sexes": sexes,
        "selected_sort": sort_key,
        "prediction_field": pred_field,
        "recycle_bin_url": "patient:recycle_bin",
    }
    return render(request, "patient/patient_list.html", context)


@login_required
@med_staff_required
@require_http_methods(["GET"])
def patient_detail(request, pk: int):
    try:
        patient: Patient = get_object_or_404(_patients_qs_for(request), pk=pk)
    except PermissionDenied:
        return _forbidden_redirect(request, _("You do not have permission to view this patient."))

    confidence_pct, confidence_angle = _compute_confidence_percent(patient)

    # on-demand AI for doctors
    if is_doctor(request.user) and confidence_pct is None:
        try:
            from patient.services import predict_and_save
            predict_and_save(patient)
            patient.refresh_from_db()
            confidence_pct, confidence_angle = _compute_confidence_percent(patient)
        except Exception:
            messages.info(request, _("AI confidence is not available yet for this record."))

    now = timezone.now()

    appt_qs = (
        Appointment.objects
        .select_related("doctor__user", "patient")
        .filter(
            patient=patient,
            doctor=patient.doctor,
            scheduled_time__isnull=False,
        )
        .exclude(status__iexact="cancelled")
    )

    last_visit = (
        appt_qs.filter(status__iexact="completed")
        .order_by("-scheduled_time")
        .first()
    )

    next_visit = (
        appt_qs.filter(status__iexact="pending", scheduled_time__gte=now)
        .order_by("scheduled_time")
        .first()
    )

    return render(
        request,
        "patient/patient_detail.html",
        {
            "patient": patient,
            "confidence": confidence_pct,
            "confidence_angle": confidence_angle,
            "last_visit": last_visit,
            "next_visit": next_visit,
        },
    )


@login_required
@med_staff_required
@require_http_methods(["GET", "POST"])
def edit_patient(request, pk: int):
    try:
        patient: Patient = get_object_or_404(_patients_qs_for(request), pk=pk)
    except PermissionDenied:
        return _forbidden_redirect(request, _("You do not have permission to edit this patient."))

    FormClass = DoctorPatientForm if is_doctor(request.user) else SecretaryPatientForm
    form = FormClass(request.POST or None, instance=patient)

    assigned_doc = _assigned_doctor_for(request.user)

    if request.method == "POST":
        if form.is_valid():
            patient = form.save(commit=False)

            # doctor assignment logic
            if is_doctor(request.user):
                if not assigned_doc:
                    return _forbidden_redirect(request, _("No doctor profile found for your account."))
                patient.doctor = assigned_doc
            else:
                # secretary
                if assigned_doc:
                    patient.doctor = assigned_doc
                else:
                    if hasattr(form, "cleaned_data") and "doctor" in form.cleaned_data and form.cleaned_data.get("doctor"):
                        patient.doctor = form.cleaned_data["doctor"]
                    elif not SECRETARY_SEES_ALL_PATIENTS:
                        return _forbidden_redirect(
                            request,
                            _("Your account is not linked to a doctor. Please assign a doctor to the secretary user or enable doctor selection in the form."),
                        )
                    # إذا SECRETARY_SEES_ALL_PATIENTS=True وماكو doctor بالحقل: نخلي doctor كما هو (ما نغيّره)

            patient.save()

            # Optional AI on save
            if _should_run_ai_on_save(request):
                try:
                    from patient.services import predict_and_save
                    predict_and_save(patient)
                    patient.refresh_from_db()
                except Exception:
                    messages.warning(request, _("Patient saved, but AI prediction could not run right now."))

            messages.success(request, _("Patient updated successfully."))
            if is_secretary(request.user):
                return redirect("patient:list")
            return redirect("patient:detail", pk=patient.pk)

        messages.error(request, _("Please correct the errors below."))

    return render(
        request,
        "patient/edit_patient.html",
        {
            "form": form,
            "patient": patient,
        },
    )


# -------------------------------------------------------------------
# Soft Delete / Recycle Bin / Restore
# -------------------------------------------------------------------
@login_required
@med_staff_required
@require_http_methods(["GET", "POST"])
def delete_patient(request, pk: int):
    """
    Soft delete patient (moves to Recycle Bin).
    """
    try:
        patient: Patient = get_object_or_404(_patients_qs_for(request), pk=pk)
    except PermissionDenied:
        return _forbidden_redirect(request, _("You do not have permission to delete this patient."))

    if request.method == "POST":
        try:
            patient.delete(user=request.user)  # type: ignore[arg-type]
            messages.success(request, _("🗑️ Patient moved to Recycle Bin."))
        except Exception:
            patient.delete()
            messages.success(request, _("🗑️ Patient moved to Recycle Bin."))
        return redirect("patient:list")

    ctx = {"patient": patient, "mode": "delete"}
    try:
        return render(request, "patient/delete_confirmation.html", ctx)
    except TemplateDoesNotExist:
        return render(request, "appointments/delete_confirmation.html", {"appointment": None, **ctx})


@login_required
@med_staff_required
@require_http_methods(["GET"])
def patient_recycle_bin(request):
    """
    List deleted patients.
    """
    try:
        qs = _patients_deleted_qs_for(request)
    except PermissionDenied:
        return _forbidden_redirect(request, _("Recycle Bin is not available for your account."))

    q = (request.GET.get("q") or "").strip()
    if q:
        qs = qs.filter(
            Q(full_name__icontains=q)
            | Q(mobile__icontains=q)
            | Q(email__icontains=q)
        )

    qs = qs.order_by("-deleted_at", "-pk") if _model_has_field(Patient, "deleted_at") else qs.order_by("-pk")

    page = Paginator(qs, PAGE_SIZE).get_page(request.GET.get("page"))
    return render(
        request,
        "patient/patient_recycle_bin.html",
        {"deleted_patients": page, "search_query": q},
    )


@login_required
@med_staff_required
@require_http_methods(["POST"])
def restore_patient(request, pk: int):
    """
    Restore a soft-deleted patient.
    """
    if not hasattr(Patient, "all_objects"):
        return _forbidden_redirect(request, _("Restore is not enabled for Patient model."))

    # Scoped restore: doctor -> his, secretary -> assigned or all (حسب setting)
    base = Patient.all_objects.select_related("doctor", "doctor__user")

    if is_doctor(request.user):
        doc = _assigned_doctor_for(request.user)
        if not doc:
            return _forbidden_redirect(request, _("No doctor profile found for your account."))
        base = base.filter(doctor=doc)
    else:
        # secretary
        doc = _assigned_doctor_for(request.user)
        if doc:
            base = base.filter(doctor=doc)
        elif not SECRETARY_SEES_ALL_PATIENTS:
            return _forbidden_redirect(request, _("No assigned doctor found for your account."))

    patient: Patient = get_object_or_404(base, pk=pk)

    is_deleted = bool(getattr(patient, "is_deleted", False))
    if not is_deleted:
        messages.info(request, _("ℹ️ This patient is not in Recycle Bin."))
        return redirect("patient:recycle_bin")

    try:
        patient.restore()
        messages.success(request, _("✅ Patient restored successfully."))
    except IntegrityError:
        messages.error(
            request,
            _("❌ Cannot restore: a conflict exists (same mobile/email already used by an active patient)."),
        )
    except ValidationError as e:
        msg = _("❌ Cannot restore patient.")
        if getattr(e, "messages", None):
            msg = f"{msg} {e.messages[0]}"
        messages.error(request, msg)

    return redirect("patient:recycle_bin")


@login_required
@med_staff_required
@require_http_methods(["GET", "POST"])
def hard_delete_patient(request, pk: int):
    """
    Permanent delete (SUPERUSER ONLY).
    """
    if not request.user.is_superuser:
        return _forbidden_redirect(request, _("Hard delete is restricted to administrators only."))

    if not hasattr(Patient, "all_objects"):
        return _forbidden_redirect(request, _("Hard delete is not enabled for Patient model."))

    patient: Patient = get_object_or_404(Patient.all_objects.select_related("doctor", "doctor__user"), pk=pk)

    if request.method == "POST":
        try:
            patient.delete(hard=True)  # type: ignore[arg-type]
        except TypeError:
            patient.delete()
        messages.success(request, _("🗑️ Patient permanently deleted."))
        return redirect("patient:recycle_bin")

    ctx = {"patient": patient, "mode": "hard_delete"}
    try:
        return render(request, "patient/delete_confirmation.html", ctx)
    except TemplateDoesNotExist:
        return render(request, "appointments/delete_confirmation.html", {"appointment": None, **ctx})


# -------------------------------------------------------------------
# Helpers used by dashboard
# -------------------------------------------------------------------
def _week_labels_counts(start: date, end: date, qs):
    grouped = (
        qs.annotate(day=TruncDate("scheduled_time"))
        .values("day")
        .annotate(count=Count("id"))
        .order_by("day")
    )
    gmap = {g["day"]: g["count"] for g in grouped}

    labels, data = [], []
    cur = start
    while cur <= end:
        labels.append(cur.strftime("%a"))
        data.append(gmap.get(cur, 0))
        cur += timedelta(days=1)
    return labels, data


@login_required
@patient_required
@require_http_methods(["GET"])
def patient_dashboard(request):
    patient_obj = getattr(request.user, "patient_profile", None) or getattr(request.user, "patient", None)
    if not patient_obj:
        raise PermissionDenied

    now = timezone.now()
    today = timezone.localdate()
    start_week = today - timedelta(days=6)
    end_week = today

    upcoming_qs = (
        Appointment.objects.select_related("doctor__user", "patient")
        .filter(patient=patient_obj, scheduled_time__gte=now)
        .exclude(status__iexact="cancelled")
        .order_by("scheduled_time")
    )
    upcoming_appointments = list(upcoming_qs[:10])
    next_appointment = upcoming_appointments[0] if upcoming_appointments else None

    week_qs = Appointment.objects.filter(
        patient=patient_obj,
        scheduled_time__date__gte=start_week,
        scheduled_time__date__lte=end_week,
    )
    labels, counts = _week_labels_counts(start_week, end_week, week_qs)
    chart_data_json = json.dumps({"labels": labels, "data": counts})

    order_fields: list[str] = []
    if hasattr(Prescription, "date_issued"):
        order_fields.append("-date_issued")
    if hasattr(Prescription, "created_at"):
        order_fields.append("-created_at")
    if not order_fields:
        order_fields = ["-id"]

    recent_prescriptions = list(
        Prescription.objects.select_related("doctor__user")
        .filter(appointment__patient=patient_obj)
        .order_by(*order_fields)[:10]
    )

    invoices = []
    if HAS_BILLING and Invoice is not None:
        base = Invoice.objects.all()
        if hasattr(Invoice, "patient"):
            base = base.filter(patient=patient_obj)
        elif hasattr(Invoice, "appointment"):
            base = base.filter(appointment__patient=patient_obj)
        if hasattr(Invoice, "created_at"):
            base = base.order_by("-created_at")
        else:
            base = base.order_by("-id")
        invoices = list(base[:10])

    profile_completion = getattr(patient_obj, "profile_completion", None)
    if profile_completion is None:
        candidate_fields = ["full_name", "mobile", "date_of_birth", "address", "sex"]
        have, total = 0, 0
        for f in candidate_fields:
            if hasattr(patient_obj, f):
                total += 1
                val = getattr(patient_obj, f)
                if val not in (None, "", []):
                    have += 1
        profile_completion = int(round((have / total) * 100)) if total else 70

    context = {
        "patient": patient_obj,
        "next_appointment": next_appointment,
        "upcoming_appointments": upcoming_appointments,
        "recent_prescriptions": recent_prescriptions,
        "invoices": invoices,
        "profile_completion": profile_completion,
        "chart_data_json": chart_data_json,
    }
    return render(request, "patient/dashboard.html", context)