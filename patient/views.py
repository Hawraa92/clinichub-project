# patient/views.py
from __future__ import annotations

import json
from datetime import date, timedelta
from typing import Final, Optional, Any

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import (
    login_required,
    permission_required,
    user_passes_test,
)
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db.models import Q, Count
from django.db.models.functions import Lower, TruncDate
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.translation import gettext as _
from django.views.decorators.http import require_http_methods

from patient.forms import DoctorPatientForm, SecretaryPatientForm
from patient.models import DiabetesStatus, Patient

from appointments.models import Appointment
from prescription.models import Prescription

try:
    from billing.models import Invoice  # type: ignore
    HAS_BILLING = True
except Exception:
    Invoice = None  # type: ignore
    HAS_BILLING = False


PAGE_SIZE: Final[int] = getattr(settings, "PATIENT_LIST_PAGE_SIZE", 25)

GROUPS_MAP = {
    "doctor": "Doctors",
    "secretary": "Secretaries",
}


def _has_role(user, role_name: str) -> bool:
    try:
        in_group = user.groups.filter(name=GROUPS_MAP.get(role_name)).exists()
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
    ✅ We want the LIST to depend on AI prediction results.
    So we prefer diabetes_prediction always.
    Fallback to diabetes_status only if diabetes_prediction doesn't exist.
    """
    if _model_has_field(Patient, "diabetes_prediction"):
        return "diabetes_prediction"
    if _model_has_field(Patient, "diabetes_status"):
        return "diabetes_status"
    # If neither exists, something is wrong with schema
    raise PermissionDenied(_("Prediction field is not available on Patient model."))


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


def _patients_qs_for(request):
    if not is_med_staff(request.user):
        raise PermissionDenied

    doc = _assigned_doctor_for(request.user)
    if not doc:
        raise PermissionDenied(_("No assigned doctor found for your account."))

    return Patient.objects.select_related("doctor", "doctor__user").filter(doctor=doc)


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
    """
    Tries to fetch proba dict from common field names.
    Supports:
    - dict already
    - JSON string
    - None / empty
    Returns normalized: keys as strings, values as floats.
    """
    candidates = (
        "prediction_proba",
        "diabetes_prediction_proba",
        "diabetes_proba",
        "proba",
    )

    raw = None
    for name in candidates:
        raw = getattr(patient, name, None)
        if raw not in (None, "", {}, []):
            break

    if raw in (None, "", {}, []):
        return {}

    # If JSON string, parse it
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
    """
    Prefer stored predicted class if present, else choose max proba key.
    We prefer diabetes_prediction (AI) first.
    """
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
    """
    Returns:
      (confidence_percent_0_100, confidence_angle_0_180)
    """
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


# -------------------------------------------------------------------
# Views
# -------------------------------------------------------------------
@login_required
@med_staff_required
@permission_required(
    "patient.add_patient",
    raise_exception=True,
)
@require_http_methods(["GET", "POST"])
def create_patient(request):
    doc = _assigned_doctor_for(request.user)
    if not doc:
        raise PermissionDenied(_("No assigned doctor found for your account."))

    FormClass = DoctorPatientForm if is_doctor(request.user) else SecretaryPatientForm
    form = FormClass(request.POST or None, initial={"doctor": doc})

    if request.method == "POST":
        if form.is_valid():
            patient: Patient = form.save(commit=False)
            patient.doctor = doc
            patient.save()

            # Run AI prediction (doctor only)
            if is_doctor(request.user):
                try:
                    from patient.services import predict_and_save
                    predict_and_save(patient)
                    patient.refresh_from_db()
                except Exception:
                    messages.warning(
                        request,
                        _("Patient saved, but AI prediction could not run right now."),
                    )

            messages.success(request, _("Patient created successfully."))

            if is_secretary(request.user):
                return redirect("patient:list")
            return redirect("patient:detail", pk=patient.pk)

        messages.error(request, _("Please correct the errors below."))

    return render(request, "patient/create_patient.html", {"form": form})


@login_required
@med_staff_required
@permission_required(
    "patient.view_patient",
    raise_exception=True,
)
@require_http_methods(["GET"])
def patient_list(request):
    qs = _patients_qs_for(request)

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

    # ✅ IMPORTANT: use AI prediction field for filters/sort/counts
    pred_field = _prediction_field_name()

    # -------------------------
    # Status filter (AI-based)
    # -------------------------
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

    # -------------------------
    # Sex filter
    # -------------------------
    try:
        sex_choices = Patient._meta.get_field("sex").choices
        allowed_sex = {choice[0] for choice in sex_choices} if sex_choices else set()
    except Exception:
        allowed_sex = set()

    sexes = [s for s in sexes if s in allowed_sex]
    if sexes:
        qs = qs.filter(sex__in=sexes)

    # -------------------------
    # Sorting
    # -------------------------
    sort_map = {
        "name_asc": Lower("full_name").asc(),
        "name_desc": Lower("full_name").desc(),
        "status": pred_field,         # ✅ sort by AI predicted class
        "recent": "-created_at",
    }
    order_by = sort_map.get(sort_key, "-created_at")
    qs = qs.order_by(order_by)

    # -------------------------
    # Counts (AI-based)
    # -------------------------
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
        # Optional: if templates want to know which field drives status
        "prediction_field": pred_field,
    }
    return render(request, "patient/patient_list.html", context)


@login_required
@med_staff_required
@permission_required(
    "patient.view_patient",
    raise_exception=True,
)
@require_http_methods(["GET"])
def patient_detail(request, pk: int):
    patient: Patient = get_object_or_404(_patients_qs_for(request), pk=pk)

    # --- AI confidence (robust) ---
    confidence_pct, confidence_angle = _compute_confidence_percent(patient)

    # If missing and user is doctor, try to run prediction once (GET side-effect but fixes UI)
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

    # ✅ Last Visit = آخر موعد "Completed" فقط
    last_visit = (
        appt_qs.filter(status__iexact="completed")
        .order_by("-scheduled_time")
        .first()
    )

    # ✅ Next Visit = أقرب موعد "Pending" بالمستقبل فقط
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
            "confidence": confidence_pct,          # 0..100 (float) or None
            "confidence_angle": confidence_angle,  # 0..180 (float) or None
            "last_visit": last_visit,
            "next_visit": next_visit,
        },
    )


@login_required
@med_staff_required
@permission_required(
    "patient.change_patient",
    raise_exception=True,
)
@require_http_methods(["GET", "POST"])
def edit_patient(request, pk: int):
    patient: Patient = get_object_or_404(_patients_qs_for(request), pk=pk)

    doc = _assigned_doctor_for(request.user)
    if not doc:
        raise PermissionDenied(_("No assigned doctor found for your account."))

    FormClass = DoctorPatientForm if is_doctor(request.user) else SecretaryPatientForm
    form = FormClass(request.POST or None, instance=patient)

    if request.method == "POST":
        if form.is_valid():
            patient = form.save(commit=False)
            patient.doctor = doc
            patient.save()

            # AI prediction after update (doctor only)
            if is_doctor(request.user):
                try:
                    from patient.services import predict_and_save
                    predict_and_save(patient)
                    patient.refresh_from_db()
                except Exception:
                    messages.warning(
                        request,
                        _("Patient saved, but AI prediction could not run right now."),
                    )

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

    order_fields = []
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
