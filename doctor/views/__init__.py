"""
doctor/views/__init__.py

✅ Stable core views + shared helpers.
✅ NO star-imports from submodules (prevents circular imports).
✅ Wrappers for visit.py / exports.py / lab.py so urls.py can reference views.* safely.
✅ Patient access includes direct assignments and appointment-linked patients.
"""

from __future__ import annotations

import csv
import json
from datetime import date, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from functools import wraps
from importlib.util import find_spec
from io import BytesIO
from typing import Any, Iterable, Tuple

from django import forms
from django.apps import apps
from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required, permission_required
from django.core.exceptions import FieldDoesNotExist, PermissionDenied
from django.core.paginator import Paginator
from django.db import models as dj_models
from django.db.models import Count, DecimalField, F, IntegerField, Min, Q, Sum, Value
from django.db.models.functions import Coalesce, TruncDate, TruncMonth
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.template import TemplateDoesNotExist
from django.template.loader import render_to_string
from django.urls import NoReverseMatch, reverse
from django.utils import timezone
from django.utils.html import escape
from django.utils.timezone import localtime, make_aware
from django.utils.translation import gettext_lazy as _
from django.views.decorators.http import require_GET, require_POST

# ✅ OrderBy (safer nulls_last across Django versions)
try:
    from django.db.models.expressions import OrderBy  # type: ignore
except Exception:  # pragma: no cover
    OrderBy = None  # type: ignore

# ✅ ExtractWeekDay/ExtractHour import (Django path may differ)
try:
    from django.db.models.functions import ExtractHour, ExtractWeekDay  # type: ignore
except Exception:  # pragma: no cover
    from django.db.models.functions.datetime import ExtractHour, ExtractWeekDay  # type: ignore

from appointments.models import Appointment
from medical_archive.models import PatientArchive
from patient.models import Patient
from prescription.models import Prescription
from ..models import Doctor


User = get_user_model()

# ------------------------------------------------------------------
# Optional libs availability
# ------------------------------------------------------------------
HAS_WEASY = find_spec("weasyprint") is not None
HAS_XLSX = find_spec("openpyxl") is not None

# ------------------------------------------------------------------
# AI note
# ------------------------------------------------------------------
AI_SUGGESTION_DISCLAIMER = "AI suggestion (rule-based). Clinician must confirm."

# ------------------------------------------------------------------
# Optional Expense model
# ------------------------------------------------------------------
Expense = None
for _path in ("finance.models", "expenses.models", "accounting.models"):
    try:
        _mod = __import__(_path, fromlist=["Expense"])
        Expense = getattr(_mod, "Expense", None)
        if Expense:
            break
    except Exception:
        Expense = None

# ------------------------------------------------------------------
# Optional LAB models (SAFE lazy resolve)
# ------------------------------------------------------------------
LAB_APP_LABELS = ("lab", "labs", "laboratory", "laboratories")
_LAB_MODELS_RESOLVED = False
LAB_REQUEST_MODEL = None
LAB_RESULT_MODEL = None

DEFAULT_PER_PAGE = 10
MAX_PER_PAGE = 100


def _get_model_any(app_labels: Iterable[str], model_names: Iterable[str]):
    for al in app_labels:
        for mn in model_names:
            try:
                m = apps.get_model(al, mn)
                if m:
                    return m
            except Exception:
                continue
    return None


def _resolve_lab_models():
    global _LAB_MODELS_RESOLVED, LAB_REQUEST_MODEL, LAB_RESULT_MODEL
    if _LAB_MODELS_RESOLVED:
        return LAB_REQUEST_MODEL, LAB_RESULT_MODEL

    try:
        LAB_REQUEST_MODEL = _get_model_any(
            LAB_APP_LABELS,
            (
                "LabOrder",
                "LabRequest",
                "TestRequest",
                "LabTestRequest",
                "AnalysisRequest",
                "LabAnalysisRequest",
            ),
        )
        LAB_RESULT_MODEL = _get_model_any(
            LAB_APP_LABELS,
            (
                "LabResult",
                "TestResult",
                "Result",
                "LabTestResult",
                "AnalysisResult",
            ),
        )
    except Exception:
        LAB_REQUEST_MODEL = None
        LAB_RESULT_MODEL = None

    _LAB_MODELS_RESOLVED = True
    return LAB_REQUEST_MODEL, LAB_RESULT_MODEL


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------
def has_field(model, name: str) -> bool:
    try:
        model._meta.get_field(name)
        return True
    except FieldDoesNotExist:
        return False


def _has_readonly_property(model_cls, name: str) -> bool:
    try:
        attr = getattr(model_cls, name)
    except Exception:
        return False
    return isinstance(attr, property) and attr.fset is None


def _safe_annotate(qs, **annotations):
    model_cls = getattr(qs, "model", None)
    if model_cls is None:
        return qs.annotate(**annotations)

    safe = {}
    for key, expr in annotations.items():
        if has_field(model_cls, key):
            continue
        if _has_readonly_property(model_cls, key):
            continue
        safe[key] = expr
    return qs.annotate(**safe) if safe else qs


def _get_field(model, name: str):
    try:
        return model._meta.get_field(name)
    except Exception:
        return None


def _is_datetime_field(model, name: str) -> bool:
    f = _get_field(model, name)
    return bool(f and isinstance(f, dj_models.DateTimeField))


def _is_date_field(model, name: str) -> bool:
    f = _get_field(model, name)
    return bool(f and isinstance(f, dj_models.DateField) and not isinstance(f, dj_models.DateTimeField))


def _first_existing_field(model, candidates: Iterable[str]) -> str | None:
    for f in candidates:
        if has_field(model, f):
            return f
    return None


def _reverse_any(*names: str, args=None, kwargs=None) -> str:
    last_err = None
    for n in names:
        try:
            return reverse(n, args=args, kwargs=kwargs)
        except NoReverseMatch as e:
            last_err = e
            continue
    if last_err:
        raise last_err
    raise NoReverseMatch("No url names provided.")


def get_doctor_for_user(user) -> Doctor | None:
    return Doctor.objects.select_related("user").filter(user=user).order_by("id").first()


def roles_allowed(*roles: str):
    """
    Allows:
    - user.role in roles
    - OR user in mapped groups (optional)
    """
    # 🔧 IMPORTANT: include external_patient as Patients (or your actual group name)
    group_lookup = {
        "doctor": "Doctors",
        "secretary": "Secretaries",
        "patient": "Patients",
        "external_patient": "Patients",
    }
    allowed_groups = [group_lookup.get(r, f"{r.title()}s") for r in roles]

    def decorator(view_func):
        @wraps(view_func)
        def _wrapped(request, *args, **kwargs):
            u = request.user
            if u.is_superuser:
                return view_func(request, *args, **kwargs)

            if getattr(u, "role", None) in roles:
                return view_func(request, *args, **kwargs)

            if u.groups.filter(name__in=allowed_groups).exists():
                return view_func(request, *args, **kwargs)

            messages.error(request, _("You do not have permission to access this page."))
            raise PermissionDenied(_("Access denied."))

        return _wrapped

    return decorator


def require_doctor_role(view_func):
    return roles_allowed("doctor")(view_func)


def permissions_required_any(*permissions: str):
    """
    Require at least one Django permission.

    This is useful for screens that can be opened through more than one
    authorized workflow, such as reports or laboratory orders/results.
    Superusers always pass. Missing permissions raise PermissionDenied so the
    project's custom 403 page is used.
    """
    normalized_permissions = tuple(
        permission.strip()
        for permission in permissions
        if permission and permission.strip()
    )

    if not normalized_permissions:
        raise ValueError("At least one permission must be supplied.")

    def decorator(view_func):
        @wraps(view_func)
        def _wrapped(request, *args, **kwargs):
            user = request.user

            if user.is_superuser:
                return view_func(request, *args, **kwargs)

            if any(user.has_perm(permission) for permission in normalized_permissions):
                return view_func(request, *args, **kwargs)

            raise PermissionDenied(_("You do not have permission to access this page."))

        return _wrapped

    return decorator


def _parse_iso_date(date_str: str | None) -> date | None:
    if not date_str:
        return None
    try:
        return date.fromisoformat(date_str)
    except Exception:
        return None


def _make_dt_start(d: date) -> datetime:
    dt = datetime.combine(d, datetime.min.time())
    if settings.USE_TZ:
        try:
            return make_aware(dt, timezone.get_current_timezone())
        except Exception:
            return dt
    return dt


def _make_dt_end(d: date) -> datetime:
    dt = datetime.combine(d, datetime.max.time())
    if settings.USE_TZ:
        try:
            return make_aware(dt, timezone.get_current_timezone())
        except Exception:
            return dt
    return dt


def _date_bounds(d: date) -> tuple[datetime, datetime]:
    return _make_dt_start(d), _make_dt_end(d)


def _normalize_date_range_params(
    date_from_str: str | None,
    date_to_str: str | None,
) -> tuple[str | None, str | None, datetime | None, datetime | None, bool, bool, bool]:
    df_raw = (date_from_str or "").strip() or None
    dt_raw = (date_to_str or "").strip() or None

    df_d = _parse_iso_date(df_raw)
    dt_d = _parse_iso_date(dt_raw)

    invalid_from = bool(df_raw and not df_d)
    invalid_to = bool(dt_raw and not dt_d)

    if invalid_from:
        df_raw, df_d = None, None
    if invalid_to:
        dt_raw, dt_d = None, None

    swapped = False
    if df_d and dt_d and df_d > dt_d:
        swapped = True
        df_d, dt_d = dt_d, df_d
        df_raw, dt_raw = dt_raw, df_raw

    df_dt = _make_dt_start(df_d) if df_d else None
    dt_dt = _make_dt_end(dt_d) if dt_d else None

    return df_raw, dt_raw, df_dt, dt_dt, swapped, invalid_from, invalid_to


def _filter_date(qs, field: str, start: datetime | None, end: datetime | None):
    model = getattr(qs, "model", None)
    if model and not has_field(model, field):
        return qs

    is_dt = bool(model and _is_datetime_field(model, field))
    is_d = bool(model and _is_date_field(model, field))

    if start:
        v = start if (is_dt or not is_d) else start.date()
        qs = qs.filter(**{f"{field}__gte": v})
    if end:
        v = end if (is_dt or not is_d) else end.date()
        qs = qs.filter(**{f"{field}__lte": v})
    return qs


def _last_day_of_month(y: int, m: int) -> date:
    if m == 12:
        return date(y, 12, 31)
    return date(y, m + 1, 1) - timedelta(days=1)


def _safe_int(v, default: int) -> int:
    try:
        return int(v)
    except Exception:
        return default


def _get_page_size(request, default: int = DEFAULT_PER_PAGE) -> int:
    per_page = _safe_int(request.GET.get("per_page"), default)
    return max(5, min(per_page, MAX_PER_PAGE))


def _get_period_dates(
    period: str,
    start_str: str | None,
    end_str: str | None,
    month_str: str | None = None,
    year_str: str | None = None,
) -> tuple[date, date]:
    today = timezone.localdate()

    if period == "week":
        start = today - timedelta(days=today.weekday())
        end = start + timedelta(days=6)
    elif period == "month":
        if month_str and year_str:
            y = _safe_int(year_str, today.year)
            m = _safe_int(month_str, today.month)
            m = max(1, min(m, 12))
            start = date(y, m, 1)
            end = _last_day_of_month(y, m)
            if y == today.year and m == today.month:
                end = today
        else:
            start = today.replace(day=1)
            end = today
    elif period == "year":
        y = _safe_int(year_str, today.year) if year_str else today.year
        start = date(y, 1, 1)
        end = date(y, 12, 31)
        if y == today.year:
            end = today
    elif period == "custom":
        try:
            start = date.fromisoformat(start_str) if start_str else today
            end = date.fromisoformat(end_str) if end_str else today
        except ValueError:
            start, end = today, today
    else:
        start = today
        end = today

    if start > end:
        start, end = end, start
    return start, end


def _resolve_report_doctor(request) -> tuple[Doctor, list[Doctor] | None, str]:
    is_super = request.user.is_superuser
    if not is_super:
        d = get_doctor_for_user(request.user)
        if not d:
            raise PermissionDenied(_("Only doctors can view this report."))
        return d, None, str(d.pk)

    doctors_qs = Doctor.objects.select_related("user").order_by("user__first_name", "user__last_name", "id")
    doctors_list = list(doctors_qs)
    if not doctors_list:
        raise Http404(_("No doctors found."))

    doctor_id_raw = (request.GET.get("doctor_id") or "").strip()
    picked = None
    if doctor_id_raw:
        picked = next((x for x in doctors_list if str(x.pk) == doctor_id_raw), None)

    target = picked or doctors_list[0]
    return target, doctors_list, str(target.pk)


def _patients_for_doctor_qs(doctor: Doctor):
    appointment_patient_ids = Appointment.objects.filter(
        doctor=doctor
    ).values_list("patient_id", flat=True)

    patient_filter = Q(id__in=appointment_patient_ids)

    if has_field(Patient, "doctor"):
        patient_filter |= Q(doctor=doctor)

    return Patient.objects.filter(patient_filter).distinct()


def _patient_select_related(qs):
    return qs.select_related("user") if has_field(Patient, "user") else qs


def _patient_order_field() -> str:
    if has_field(Patient, "full_name"):
        return "full_name"
    if has_field(Patient, "name"):
        return "name"
    return "id"


def _user_display_name(u) -> str:
    if not u:
        return ""
    try:
        full = (u.get_full_name() or "").strip()
    except Exception:
        full = ""
    if full:
        return full
    for attr in ("username", "email"):
        v = (getattr(u, attr, None) or "").strip()
        if v:
            return v
    return ""


def _csv_dt(v) -> str:
    if not v:
        return ""
    try:
        if isinstance(v, datetime):
            try:
                if settings.USE_TZ:
                    v = localtime(v)
            except Exception:
                pass
            return v.strftime("%Y-%m-%d %H:%M")
        if isinstance(v, date):
            return v.isoformat()
    except Exception:
        pass
    return str(v)


def _patient_display_name(p: Patient) -> str:
    if not p:
        return ""

    for attr in ("full_name", "name"):
        try:
            v = getattr(p, attr, None)
            if isinstance(v, str) and v.strip():
                return v.strip()
        except Exception:
            pass

    try:
        u = getattr(p, "user", None)
        if u:
            full = (u.get_full_name() or "").strip()
            if full:
                return full
            for attr in ("username", "email"):
                v = (getattr(u, attr, None) or "").strip()
                if v:
                    return v
    except Exception:
        pass

    try:
        return str(p)
    except Exception:
        return ""


def _ensure_patient_template_attrs(p: Patient) -> None:
    if not p:
        return

    display = _patient_display_name(p)

    if (not has_field(Patient, "name")) and (not _has_readonly_property(Patient, "name")):
        try:
            setattr(p, "name", display)
        except Exception:
            pass

    if (not has_field(Patient, "full_name")) and (not _has_readonly_property(Patient, "full_name")):
        try:
            setattr(p, "full_name", display)
        except Exception:
            pass


# ------------------------------------------------------------------
# Core select_related
# ------------------------------------------------------------------
def _appt_select_related(qs):
    qs = qs.select_related("patient", "doctor", "doctor__user")
    if has_field(Patient, "user"):
        try:
            qs = qs.select_related("patient__user")
        except Exception:
            pass
    return qs


# ------------------------------------------------------------------
# ✅ Core views referenced directly by urls.py
# ------------------------------------------------------------------
@login_required
@require_doctor_role
def doctor_dashboard(request):
    doctor = get_doctor_for_user(request.user)
    if not doctor:
        raise Http404(_("Doctor profile not found."))

    user = request.user
    can_view_appointments = user.has_perm("appointments.view_appointment")
    can_view_patients = user.has_perm("patient.view_patient")
    can_view_archives = user.has_perm("medical_archive.view_patientarchive")
    can_view_prescriptions = user.has_perm("prescription.view_prescription")

    today = timezone.localdate()
    start_week = today - timedelta(days=6)
    today_start, today_end = _date_bounds(today)
    week_start, week_end = _make_dt_start(start_week), _make_dt_end(today)

    # Safe defaults: the dashboard remains accessible even when the doctor has
    # no operational permissions, but no protected clinical data is queried.
    recent_archives = PatientArchive.objects.none()
    total_archives = 0
    total_prescriptions = 0
    unique_patients = 0
    today_appointments: list[Appointment] = []
    todays_count = 0
    patients_today = 0
    new_patients_today = 0

    week_labels = [
        (start_week + timedelta(days=index)).strftime("%a")
        for index in range(7)
    ]
    week_counts = [0] * 7

    if can_view_archives:
        recent_archives_qs = PatientArchive.objects.all()

        if has_field(PatientArchive, "doctor"):
            recent_archives_qs = recent_archives_qs.filter(doctor=doctor)

        if has_field(PatientArchive, "patient"):
            try:
                recent_archives_qs = recent_archives_qs.select_related("patient")
            except Exception:
                pass

        if has_field(PatientArchive, "created_at"):
            recent_archives = recent_archives_qs.order_by("-created_at")[:5]
        else:
            recent_archives = recent_archives_qs.order_by("-id")[:5]

        total_archives = (
            PatientArchive.objects.filter(doctor=doctor).count()
            if has_field(PatientArchive, "doctor")
            else PatientArchive.objects.count()
        )

    if can_view_prescriptions:
        total_prescriptions = (
            Prescription.objects.filter(doctor=doctor).count()
            if has_field(Prescription, "doctor")
            else Prescription.objects.count()
        )

    if can_view_appointments:
        appointment_scope = Appointment.objects.filter(
            doctor=doctor,
            scheduled_time__isnull=False,
        )

        todays_qs = _appt_select_related(appointment_scope)
        todays_qs = _filter_date(
            todays_qs,
            "scheduled_time",
            today_start,
            today_end,
        ).order_by("scheduled_time")

        today_appointments = list(todays_qs)

        for appointment in today_appointments:
            try:
                _ensure_patient_template_attrs(
                    getattr(appointment, "patient", None)
                )
            except Exception:
                pass

        todays_count = len(today_appointments)
        patients_today = len(
            {
                getattr(appointment, "patient_id", None)
                for appointment in today_appointments
                if getattr(appointment, "patient_id", None)
            }
        )

        week_qs = _filter_date(
            appointment_scope,
            "scheduled_time",
            week_start,
            week_end,
        )
        week_data = (
            week_qs.annotate(day=TruncDate("scheduled_time"))
            .values("day")
            .annotate(count=Count("id"))
            .order_by("day")
        )
        week_map = {
            entry["day"]: entry["count"]
            for entry in week_data
        }
        week_counts = [
            week_map.get(start_week + timedelta(days=index), 0)
            for index in range(7)
        ]

        if can_view_patients:
            unique_patients = (
                appointment_scope.values("patient_id")
                .distinct()
                .count()
            )

            if _is_datetime_field(Appointment, "scheduled_time"):
                new_patients_today = (
                    appointment_scope.values("patient_id")
                    .annotate(first_dt=Min("scheduled_time"))
                    .filter(
                        first_dt__gte=today_start,
                        first_dt__lte=today_end,
                    )
                    .count()
                )

    context = {
        "doctor": doctor,
        "recent_archives": recent_archives,
        "unique_patients": unique_patients,
        "chart_data_json": json.dumps({"labels": week_labels, "data": week_counts}),
        "today_appointments": today_appointments,
        "stats": {
            "patients_today": patients_today,
            "appointments_today": todays_count,
            "new_patients_today": new_patients_today,
            "total_archives": total_archives,
            "total_prescriptions": total_prescriptions,
            "prescription_count": total_prescriptions,
        },
    }
    return render(request, "doctor/doctor_dashboard.html", context)


@login_required
@require_doctor_role
@permission_required("doctor.view_doctor", raise_exception=True)
def doctor_detail(request, pk: int):
    if not request.user.is_superuser:
        me = get_doctor_for_user(request.user)
        if not me or me.pk != pk:
            raise PermissionDenied(_("Access denied."))
    doctor = get_object_or_404(Doctor.objects.select_related("user"), pk=pk)
    return render(request, "doctor/doctor_detail.html", {"doctor": doctor})


@require_GET
def doctor_public_profile(request, pk: int):
    qs = Doctor.objects.select_related("user")
    if has_field(Doctor, "specialty_profile"):
        qs = qs.select_related("specialty_profile")
    doctor = get_object_or_404(qs, pk=pk)

    spec_label = "General Practice"
    try:
        if has_field(Doctor, "specialty_profile") and getattr(doctor, "specialty_profile", None):
            spec_label = doctor.specialty_profile.name or spec_label
        elif has_field(Doctor, "specialty") and getattr(doctor, "specialty", ""):
            spec_label = doctor.specialty or spec_label
    except Exception:
        pass

    ctx = {"doctor": doctor, "spec_label": spec_label, "back_url": None}
    try:
        ctx["back_url"] = _reverse_any("doctor:available_doctors", "doctor:available", "doctor:available_doctors_list")
    except Exception:
        ctx["back_url"] = None

    return render(request, "doctor/doctor_public_profile.html", ctx)


@login_required
@require_doctor_role
@permission_required("patient.view_patient", raise_exception=True)
def patients_list(request):
    doctor = get_doctor_for_user(request.user)
    if not doctor:
        raise Http404()

    qs = _patients_for_doctor_qs(doctor)

    q = (request.GET.get("q") or "").strip()
    if q:
        look = Q()
        if q.isdigit():
            look |= Q(id=int(q))
        if has_field(Patient, "full_name"):
            look |= Q(full_name__icontains=q)
        if has_field(Patient, "name"):
            look |= Q(name__icontains=q)
        if has_field(Patient, "mobile"):
            look |= Q(mobile__icontains=q)
        if has_field(Patient, "email"):
            look |= Q(email__icontains=q)
        qs = qs.filter(look)

    qs = _patient_select_related(qs).distinct().order_by(_patient_order_field())
    return render(
        request,
        "doctor/patient_records.html",
        {"doctor": doctor, "patients": qs, "query": q, "search_query": q},
    )


@login_required
@require_doctor_role
@permission_required("patient.view_patient", raise_exception=True)
def patient_search(request):
    return patients_list(request)


@login_required
@require_doctor_role
@permission_required(
    ("patient.view_patient", "doctor.view_doctorvisit"),
    raise_exception=True,
)
def report_search(request):
    doctor = get_doctor_for_user(request.user)
    if not doctor:
        raise Http404()

    pid = (request.GET.get("patient") or "").strip()
    if pid:
        if not pid.isdigit():
            messages.error(request, _("Invalid patient id."))
            return redirect(_reverse_any("doctor:report_search", "doctor:patient_search"))
        return redirect(_reverse_any("doctor:patient_report", args=[int(pid)]))

    patients = _patient_select_related(_patients_for_doctor_qs(doctor)).distinct().order_by(_patient_order_field())
    return render(request, "doctor/patient_search.html", {"doctor": doctor, "patients": patients})


def _load_report_data(
    doctor: Doctor,
    patient: Patient,
    date_from_str: str | None,
    date_to_str: str | None,
) -> Tuple[Any, Any, Any]:
    _df_str, _dt_str, df, dt, _swapped, _inv_f, _inv_t = _normalize_date_range_params(date_from_str, date_to_str)

    archive_date_field = _first_existing_field(PatientArchive, ("created_at", "created_on", "date", "created"))
    arch_qs = PatientArchive.objects.all()
    if has_field(PatientArchive, "patient"):
        arch_qs = arch_qs.filter(patient=patient)
    if has_field(PatientArchive, "doctor"):
        arch_qs = arch_qs.filter(doctor=doctor)
    if archive_date_field:
        arch_qs = _filter_date(arch_qs, archive_date_field, df, dt).order_by(f"-{archive_date_field}")
    else:
        arch_qs = arch_qs.order_by("-id")

    presc_date_field = _first_existing_field(Prescription, ("date_issued", "issued_at", "created_at", "date"))
    presc_qs = Prescription.objects.all()
    if has_field(Prescription, "doctor"):
        presc_qs = presc_qs.filter(doctor=doctor)
    if has_field(Prescription, "appointment"):
        presc_qs = presc_qs.filter(appointment__patient=patient)
    elif has_field(Prescription, "patient"):
        presc_qs = presc_qs.filter(patient=patient)
    if presc_date_field:
        presc_qs = _filter_date(presc_qs, presc_date_field, df, dt).order_by(f"-{presc_date_field}")
    else:
        presc_qs = presc_qs.order_by("-id")

    appointments = _filter_date(
        Appointment.objects.filter(patient=patient, doctor=doctor, scheduled_time__isnull=False),
        "scheduled_time",
        df,
        dt,
    ).order_by("-scheduled_time")

    return arch_qs, presc_qs, appointments


@login_required
@require_doctor_role
@permission_required(
    ("patient.view_patient", "doctor.view_doctorvisit"),
    raise_exception=True,
)
def patient_report(request, patient_id: int):
    doctor = get_doctor_for_user(request.user)
    if not doctor:
        raise Http404()

    patient = get_object_or_404(_patients_for_doctor_qs(doctor), id=patient_id)
    archives, prescriptions, appointments = _load_report_data(
        doctor,
        patient,
        request.GET.get("date_from"),
        request.GET.get("date_to"),
    )

    try:
        archives = archives.select_related("doctor__user", "patient")
    except Exception:
        pass
    try:
        appointments = appointments.select_related("doctor__user", "patient")
        if has_field(Patient, "user"):
            appointments = appointments.select_related("patient__user")
    except Exception:
        pass
    try:
        prescriptions = prescriptions.select_related("doctor__user")
    except Exception:
        pass

    return render(
        request,
        "doctor/report_patient.html",
        {
            "doctor": doctor,
            "patient": patient,
            "archives": archives,
            "prescriptions": prescriptions,
            "appointments": appointments,
            "now": timezone.now(),
            "date_from": request.GET.get("date_from"),
            "date_to": request.GET.get("date_to"),
        },
    )


# ✅✅✅ FIX: allow patients/external patients to see /doctor/available/
@login_required
@roles_allowed("doctor", "secretary", "patient", "external_patient")
def available_doctors_list(request):
    qs = Doctor.objects.select_related("user")

    if has_field(Doctor, "specialty_profile"):
        try:
            qs = qs.select_related("specialty_profile")
        except Exception:
            pass

    # ----- Collect specialties for template buttons -----
    specialties: list[str] = []
    try:
        if has_field(Doctor, "specialty_profile"):
            vals = (
                Doctor.objects.exclude(specialty_profile__isnull=True)
                .select_related("specialty_profile")
                .values_list("specialty_profile__name", flat=True)
                .distinct()
            )
            specialties = sorted([v for v in vals if v])
        elif has_field(Doctor, "specialty"):
            vals = Doctor.objects.values_list("specialty", flat=True).distinct()
            specialties = sorted([v for v in vals if v])
    except Exception:
        specialties = []

    # ----- Filters -----
    q = (request.GET.get("q") or "").strip()
    if q:
        look = Q()
        # name sources
        if has_field(Doctor, "full_name"):
            look |= Q(full_name__icontains=q)
        if has_field(Doctor, "name"):
            look |= Q(name__icontains=q)

        # user name/email/username
        look |= Q(user__first_name__icontains=q) | Q(user__last_name__icontains=q) | Q(user__username__icontains=q)
        if hasattr(User, "email"):
            look |= Q(user__email__icontains=q)

        # specialty fields
        if has_field(Doctor, "specialty"):
            look |= Q(specialty__icontains=q)
        if has_field(Doctor, "specialty_profile"):
            look |= Q(specialty_profile__name__icontains=q)

        qs = qs.filter(look)

    specialty = (request.GET.get("specialty") or "").strip()
    if specialty:
        if has_field(Doctor, "specialty_profile"):
            qs = qs.filter(specialty_profile__name=specialty)
        elif has_field(Doctor, "specialty"):
            qs = qs.filter(specialty=specialty)

    # online filter
    online = (request.GET.get("online") or "").strip()
    online_field = None
    for f in ("available", "is_online", "online"):
        if has_field(Doctor, f):
            online_field = f
            break
    if online == "1" and online_field:
        qs = qs.filter(**{online_field: True})

    # rating filter
    min_rating = (request.GET.get("min_rating") or "").strip()
    if min_rating and has_field(Doctor, "rating"):
        try:
            qs = qs.filter(rating__gte=float(min_rating))
        except Exception:
            pass

    # fee range
    if has_field(Doctor, "consultation_fee"):
        min_fee = (request.GET.get("min_fee") or "").strip()
        max_fee = (request.GET.get("max_fee") or "").strip()
        if min_fee:
            try:
                qs = qs.filter(consultation_fee__gte=int(min_fee))
            except Exception:
                pass
        if max_fee:
            try:
                qs = qs.filter(consultation_fee__lte=int(max_fee))
            except Exception:
                pass

    # ----- Sorting -----
    sort = (request.GET.get("sort") or "rating").strip()

    rating_field = "rating" if has_field(Doctor, "rating") else None
    exp_field = None
    for f in ("experience_years", "experience"):
        if has_field(Doctor, f):
            exp_field = f
            break

    if sort == "experience" and exp_field:
        # most experienced
        qs = qs.order_by(F(exp_field).desc(nulls_last=True), "id") if hasattr(F(exp_field), "desc") else qs.order_by(f"-{exp_field}", "id")
    elif sort == "availability" and online_field:
        # available first, then rating
        if rating_field:
            qs = qs.order_by(F(online_field).desc(nulls_last=True), F(rating_field).desc(nulls_last=True), "id") if hasattr(F(online_field), "desc") else qs.order_by(f"-{online_field}", f"-{rating_field}", "id")
        else:
            qs = qs.order_by(F(online_field).desc(nulls_last=True), "id") if hasattr(F(online_field), "desc") else qs.order_by(f"-{online_field}", "id")
    else:
        # highest rated default
        if rating_field:
            qs = qs.order_by(F(rating_field).desc(nulls_last=True), "id") if hasattr(F(rating_field), "desc") else qs.order_by(f"-{rating_field}", "id")
        else:
            qs = qs.order_by("id")

    # ----- Online count for header -----
    online_doctors_count = 0
    try:
        if online_field:
            online_doctors_count = Doctor.objects.filter(**{online_field: True}).count()
    except Exception:
        online_doctors_count = 0

    # Pagination
    paginator = Paginator(qs, 12)
    page_obj = paginator.get_page(request.GET.get("page"))

    return render(
        request,
        "doctor/available_doctors.html",
        {
            "doctors": page_obj,
            "page_obj": page_obj,
            "specialties": specialties,
            "online_doctors_count": online_doctors_count,
        },
    )


@login_required
@require_doctor_role
@permission_required("doctor.change_doctor", raise_exception=True)
def doctor_toggle_availability(request):
    if request.method != "POST":
        raise Http404()

    doctor = get_doctor_for_user(request.user)
    if not doctor:
        raise Http404(_("Doctor profile not found."))

    changed = False
    if has_field(Doctor, "available"):
        try:
            doctor.available = not bool(getattr(doctor, "available"))
            changed = True
        except Exception:
            pass

    for f in ("is_online", "online"):
        if has_field(Doctor, f):
            try:
                setattr(doctor, f, not bool(getattr(doctor, f)))
                changed = True
                break
            except Exception:
                continue

    if changed:
        try:
            doctor.save(update_fields=[f for f in ("available", "is_online", "online") if has_field(Doctor, f)])
        except Exception:
            doctor.save()
        messages.success(request, _("Availability updated."))
    else:
        messages.warning(request, _("No availability fields found on Doctor model."))

    return redirect(_reverse_any("doctor:dashboard"))


# ------------------------------------------------------------------
# ✅ Wrappers for submodule views
# (so urls.py can reference views.* without importing submodules at startup)
# ------------------------------------------------------------------
@login_required
@require_doctor_role
@permission_required(
    ("appointments.view_appointment", "doctor.add_doctorvisit"),
    raise_exception=True,
)
def doctor_visit(request, appointment_id: int, *args, **kwargs):
    from .visit import doctor_visit as _v
    return _v(request, appointment_id, *args, **kwargs)


@login_required
@require_doctor_role
@permission_required(
    ("appointments.view_appointment", "doctor.add_doctorvisit"),
    raise_exception=True,
)
def visit_ai_assist(request, appointment_id: int, *args, **kwargs):
    from .visit import visit_ai_assist as _v
    return _v(request, appointment_id, *args, **kwargs)


@login_required
@require_doctor_role
@permission_required(
    ("patient.view_patient", "doctor.view_doctorvisit"),
    raise_exception=True,
)
def report_pdf(request, patient_id: int, *args, **kwargs):
    from .exports import report_pdf as _v
    return _v(request, patient_id, *args, **kwargs)


@login_required
@require_doctor_role
@permission_required(
    ("patient.view_patient", "doctor.view_doctorvisit"),
    raise_exception=True,
)
def report_csv(request, patient_id: int, *args, **kwargs):
    from .exports import report_csv as _v
    return _v(request, patient_id, *args, **kwargs)


@login_required
@require_doctor_role
@permissions_required_any(
    "appointments.view_appointment",
    "doctor.view_doctorvisit",
)
def doctor_reports(request, *args, **kwargs):
    from .exports import doctor_reports as _v
    return _v(request, *args, **kwargs)


@login_required
@require_doctor_role
@permissions_required_any(
    "appointments.view_appointment",
    "doctor.view_doctorvisit",
)
def doctor_reports_export(request, *args, **kwargs):
    from .exports import doctor_reports_export as _v
    return _v(request, *args, **kwargs)


@login_required
@require_doctor_role
@permissions_required_any(
    "appointments.view_appointment",
    "doctor.view_doctorvisit",
)
def doctor_reports_pdf(request, *args, **kwargs):
    from .exports import doctor_reports_pdf as _v
    return _v(request, *args, **kwargs)


@login_required
@require_doctor_role
@permissions_required_any(
    "lab.view_laborder",
    "lab.view_labresult",
)
def doctor_lab_requests(request, *args, **kwargs):
    from .lab import doctor_lab_requests as _v
    return _v(request, *args, **kwargs)


@login_required
@require_doctor_role
@permissions_required_any(
    "lab.view_laborder",
    "lab.view_labresult",
)
def doctor_lab_request_detail(request, request_id: int, *args, **kwargs):
    from .lab import doctor_lab_request_detail as _v
    return _v(request, request_id, *args, **kwargs)