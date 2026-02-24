# doctor/views/helpers.py
from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from functools import wraps
from importlib.util import find_spec
from typing import Any, Iterable

from django.apps import apps
from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.core.exceptions import FieldDoesNotExist, PermissionDenied
from django.core.paginator import Paginator
from django.db import models as dj_models
from django.db.models import DecimalField, F, IntegerField, Value
from django.urls import NoReverseMatch, reverse
from django.utils import timezone
from django.utils.timezone import localtime, make_aware
from django.utils.translation import gettext_lazy as _

from patient.models import Patient
from ..models import Doctor

User = get_user_model()

# ------------------------------------------------------------------
# Optional libs availability
# ------------------------------------------------------------------
HAS_WEASY = find_spec("weasyprint") is not None
HAS_XLSX = find_spec("openpyxl") is not None

DEFAULT_PER_PAGE = 10
MAX_PER_PAGE = 100

# ------------------------------------------------------------------
# ✅ AI note (rule-based helper, not a diagnosis)
# ------------------------------------------------------------------
AI_SUGGESTION_DISCLAIMER = "AI suggestion (rule-based). Clinician must confirm."

# ------------------------------------------------------------------
# ✅ OrderBy (safer nulls_last across Django versions)
# ------------------------------------------------------------------
try:
    from django.db.models.expressions import OrderBy  # type: ignore
except Exception:  # pragma: no cover
    OrderBy = None  # type: ignore

# ✅ ExtractWeekDay/ExtractHour import (Django path may differ)
try:
    from django.db.models.functions import ExtractHour, ExtractWeekDay  # type: ignore
except Exception:  # pragma: no cover
    from django.db.models.functions.datetime import ExtractHour, ExtractWeekDay  # type: ignore

__all__ = [
    # constants
    "AI_SUGGESTION_DISCLAIMER",
    "HAS_WEASY",
    "HAS_XLSX",
    "DEFAULT_PER_PAGE",
    "MAX_PER_PAGE",
    "OrderBy",
    "ExtractHour",
    "ExtractWeekDay",
    # role helpers
    "roles_allowed",
    "require_doctor_role",
    "get_doctor_for_user",
    # field helpers
    "has_field",
    "_has_readonly_property",
    "_safe_annotate",
    "_first_existing_field",
    "_is_datetime_field",
    "_is_date_field",
    # datetime helpers
    "_parse_iso_date",
    "_make_dt_start",
    "_make_dt_end",
    "_date_bounds",
    "_normalize_date_range_params",
    "_filter_date",
    "_last_day_of_month",
    "_get_period_dates",
    # misc helpers
    "_safe_int",
    "_get_page_size",
    "_reverse_any",
    "_user_display_name",
    "_csv_dt",
    "_patient_display_name",
    "_ensure_patient_template_attrs",
    "_appt_select_related",
]

# ------------------------------------------------------------------
# Model/field helpers
# ------------------------------------------------------------------
def has_field(model, name: str) -> bool:
    try:
        model._meta.get_field(name)
        return True
    except FieldDoesNotExist:
        return False


def _has_readonly_property(model_cls, name: str) -> bool:
    """True if name is a read-only @property (no setter)."""
    try:
        attr = getattr(model_cls, name)
    except Exception:
        return False
    return isinstance(attr, property) and attr.fset is None


def _safe_annotate(qs, **annotations):
    """
    Annotate only when safe:
    - don't override real DB fields
    - don't override read-only @property attrs
    """
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


# ------------------------------------------------------------------
# URL reverse helper
# ------------------------------------------------------------------
def _reverse_any(*names: str, args=None, kwargs=None) -> str:
    """Try multiple URL names (helps avoid NoReverseMatch when renaming urls)."""
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


# ------------------------------------------------------------------
# Doctor/user role helpers
# ------------------------------------------------------------------
def get_doctor_for_user(user) -> Doctor | None:
    """Return the Doctor instance attached to a user (or None)."""
    return Doctor.objects.select_related("user").filter(user=user).order_by("id").first()


def roles_allowed(*roles: str):
    """
    Decorator restricting access to specific user roles.
    Superusers bypass the check.
    Supports:
    - user.role
    - group membership (Doctors / Secretaries / Patients)
    """
    group_lookup = {"doctor": "Doctors", "secretary": "Secretaries", "patient": "Patients"}
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


# ------------------------------------------------------------------
# Date/time helpers
# ------------------------------------------------------------------
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
    """
    Returns:
      (df_raw, dt_raw, df_dt, dt_dt, swapped, invalid_from, invalid_to)
    """
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


# ------------------------------------------------------------------
# Display helpers
# ------------------------------------------------------------------
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
    """
    Some templates expect patient.name / patient.full_name.
    If your Patient model doesn't have these fields, we safely attach them at runtime.
    """
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
    """
    Safe select_related for Appointment -> patient + (patient.user if exists) + doctor + doctor.user
    """
    qs = qs.select_related("patient", "doctor", "doctor__user")
    if has_field(Patient, "user"):
        try:
            qs = qs.select_related("patient__user")
        except Exception:
            pass
    return qs
