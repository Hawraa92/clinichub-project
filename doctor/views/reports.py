# doctor/views/reports.py
from __future__ import annotations

import calendar
import logging
from datetime import date, datetime
from typing import Any

from django.core.paginator import Paginator
from django.db.models import Count, Min, Sum
from django.db.models.functions import TruncDate, TruncMonth
from django.http import Http404

# ExtractHour import path can vary across Django versions
try:
    from django.db.models.functions import ExtractHour  # type: ignore
except Exception:  # pragma: no cover
    from django.db.models.functions.datetime import ExtractHour  # type: ignore

from appointments.models import Appointment

# -------------------------------------------------------------------
# Import shared helpers/constants from doctor.views package (__init__.py)
# NOTE: __init__.py in your project does NOT import reports.py, so this is safe.
# -------------------------------------------------------------------
from . import (  # noqa: E402
    HAS_WEASY,
    HAS_XLSX,
    get_doctor_for_user,
    has_field,
    _resolve_report_doctor,
    _get_period_dates,
    _make_dt_start,
    _make_dt_end,
    _filter_date,
    _appt_select_related,
    _user_display_name,
    _patient_display_name,
)

logger = logging.getLogger(__name__)

# Optional expenses model (keep simple; you can extend later)
# If you actually have Expense model, replace this with a proper import/query.
HAS_EXPENSES = False


# -------------------------------------------------------------------
# Small utilities
# -------------------------------------------------------------------
def _safe_int(v: Any, default: int) -> int:
    try:
        return int(v)
    except Exception:
        return default


def _page_size(request, default: int = 10) -> int:
    per_page = _safe_int(request.GET.get("per_page"), default)
    return max(5, min(per_page, 100))


def _month_choices() -> list[tuple[int, str]]:
    return [(i, calendar.month_abbr[i]) for i in range(1, 13)]


def _money_sum(qs) -> int:
    """
    Safely sum IQD amount if field exists.
    """
    if not has_field(Appointment, "iqd_amount"):
        return 0
    agg = qs.aggregate(s=Sum("iqd_amount"))
    try:
        return int(agg["s"] or 0)
    except Exception:
        return 0


def _enforce_report_doctor_isolation(request, report_doctor, doctors_list, selected_doctor_id):
    """
    Defense-in-depth:
    Even if _resolve_report_doctor() misbehaves, a non-superuser doctor must only see own reports.
    - Superuser: unchanged
    - Doctor user: forced to own doctor profile
    """
    if getattr(request.user, "is_superuser", False):
        return report_doctor, doctors_list, selected_doctor_id

    viewer_doctor = get_doctor_for_user(request.user)
    if not viewer_doctor:
        raise Http404("Doctor profile not found.")

    if not report_doctor:
        # Fail-safe: fallback to own doctor
        logger.warning(
            "reports._build_doctor_reports_payload: _resolve_report_doctor returned None "
            "for non-superuser user_id=%s. Falling back to own doctor_id=%s.",
            getattr(request.user, "pk", None),
            getattr(viewer_doctor, "pk", None),
        )
        return viewer_doctor, [], getattr(viewer_doctor, "pk", None)

    if getattr(report_doctor, "pk", None) != getattr(viewer_doctor, "pk", None):
        logger.warning(
            "Doctor report isolation enforced. user_id=%s attempted report_doctor_id=%s; forced to own doctor_id=%s.",
            getattr(request.user, "pk", None),
            getattr(report_doctor, "pk", None),
            getattr(viewer_doctor, "pk", None),
        )
        return viewer_doctor, [], getattr(viewer_doctor, "pk", None)

    # For doctor users, no need to expose doctors dropdown list
    return viewer_doctor, [], getattr(viewer_doctor, "pk", None)


# -------------------------------------------------------------------
# Fallback HTML builder (used by exports.py if template missing)
# -------------------------------------------------------------------
def _fallback_doctor_reports_pdf_html(ctx: dict[str, Any]) -> str:
    """
    Minimal HTML fallback for PDF/HTML rendering if templates are missing.
    """
    report_doctor = ctx.get("report_doctor")
    start = ctx.get("start")
    end = ctx.get("end")
    appointments = ctx.get("appointments") or []
    summary = ctx.get("summary") or {}

    def esc(x: Any) -> str:
        return str(x or "").replace("<", "&lt;").replace(">", "&gt;")

    doc_name = esc(_user_display_name(getattr(report_doctor, "user", None))) if report_doctor else "Doctor"
    total = esc(summary.get("total", 0))
    completed = esc(summary.get("completed", 0))
    revenue = esc(summary.get("revenue", 0))

    rows = ""
    for a in appointments:
        st = getattr(a, "scheduled_time", None)
        pid = esc(getattr(a, "pk", ""))
        dt = esc(st)
        pat = esc(_patient_display_name(getattr(a, "patient", None)))
        status = esc(getattr(a, "status", ""))
        amount = esc(getattr(a, "iqd_amount", "")) if has_field(Appointment, "iqd_amount") else ""
        rows += f"<tr><td>{pid}</td><td>{dt}</td><td>{pat}</td><td>{status}</td><td>{amount}</td></tr>"

    return f"""
<!doctype html>
<html>
<head>
  <meta charset="utf-8" />
  <title>Doctor Reports</title>
  <style>
    body {{ font-family: Arial, sans-serif; font-size: 12px; }}
    h1 {{ font-size: 18px; margin: 0 0 10px; }}
    .meta {{ color: #555; margin: 6px 0 14px; }}
    table {{ width: 100%; border-collapse: collapse; }}
    th, td {{ border: 1px solid #ccc; padding: 6px; }}
    th {{ background: #f3f3f3; }}
  </style>
</head>
<body>
  <h1>Reports & Analytics</h1>
  <div class="meta">
    <div><b>Doctor:</b> {doc_name}</div>
    <div><b>Period:</b> {esc(start)} → {esc(end)}</div>
    <div><b>Total:</b> {total} | <b>Completed:</b> {completed} | <b>Revenue:</b> {revenue}</div>
  </div>

  <table>
    <tr><th>ID</th><th>Scheduled</th><th>Patient</th><th>Status</th><th>IQD</th></tr>
    {rows}
  </table>
</body>
</html>
"""


# -------------------------------------------------------------------
# Main payload builder for doctor_reports.html
# -------------------------------------------------------------------
def _build_doctor_reports_payload(request, for_pdf: bool = False) -> dict[str, Any]:
    """
    Builds the complete context expected by templates/doctor/doctor_reports.html

    Provides:
    - doctors, selected_doctor_id, report_doctor
    - period/status/month/year/start/end/per_page
    - appointments, page_obj
    - summary dict (total, completed, revenue, unique_patients, etc.)
    - daily (chart data), status_breakdown (chart data), monthly (chart data if has_money)
    - best_hour_visits, best_hour_revenue

    Notes:
    - for_pdf=True disables pagination so exported PDF receives all rows.
    - Doctor isolation is enforced again here (defense-in-depth).
    """
    # Doctor resolution:
    # - Superuser: can select doctor_id
    # - Doctor: sees own reports
    report_doctor, doctors_list, selected_doctor_id = _resolve_report_doctor(request)

    # Defense-in-depth isolation guard (important)
    report_doctor, doctors_list, selected_doctor_id = _enforce_report_doctor_isolation(
        request,
        report_doctor,
        doctors_list,
        selected_doctor_id,
    )

    if not report_doctor:
        raise Http404("Doctor not found.")

    # Filters
    period = (request.GET.get("period") or "month").strip().lower()
    if period not in {"day", "week", "month", "year", "custom"}:
        period = "month"

    status_field = "status" if has_field(Appointment, "status") else None
    status = (request.GET.get("status") or "").strip().lower()
    if status not in {"completed", "pending", "cancelled"}:
        status = ""

    month_sel = (request.GET.get("month") or "").strip()
    year_sel = (request.GET.get("year") or "").strip()

    # Date range (dates)
    start_date, end_date = _get_period_dates(
        period,
        request.GET.get("start"),
        request.GET.get("end"),
        month_str=month_sel or None,
        year_str=year_sel or None,
    )

    # Convert dates -> datetimes (for filtering scheduled_time)
    start_dt = _make_dt_start(start_date)
    end_dt = _make_dt_end(end_date)

    # Base query (doctor-isolated)
    qs = Appointment.objects.filter(
        doctor=report_doctor,
        scheduled_time__isnull=False,
    )
    qs = _appt_select_related(qs)
    qs = _filter_date(qs, "scheduled_time", start_dt, end_dt).order_by("scheduled_time")

    if status and status_field:
        qs = qs.filter(**{status_field: status})

    has_money = has_field(Appointment, "iqd_amount")

    # Pagination / row source
    per_page = _page_size(request, default=10)
    page_obj = None
    appointments_for_template = None

    if for_pdf:
        # IMPORTANT: PDF should include all rows (not paginated page only)
        appointments_for_template = qs
    else:
        paginator = Paginator(qs, per_page)
        page_number = request.GET.get("page")
        page_obj = paginator.get_page(page_number)
        appointments_for_template = page_obj

    # Summary metrics
    total = qs.count()

    completed = 0
    if status_field:
        try:
            completed = qs.filter(**{status_field: "completed"}).count()
        except Exception:
            logger.exception("Failed to count completed appointments for doctor reports.")
            completed = 0

    unique_patients = 0
    try:
        unique_patients = qs.values("patient_id").distinct().count()
    except Exception:
        logger.exception("Failed to calculate unique patients for doctor reports.")
        unique_patients = 0

    revenue = _money_sum(qs) if has_money else 0
    completion_rate = (completed / total * 100.0) if total else 0.0

    # New/Returning (best-effort, consistent with selected status filter)
    # New = patients whose first appointment time (within the filtered status scope)
    #       is inside the selected period.
    new_patients = 0
    returning_patients = 0
    try:
        firsts_base = Appointment.objects.filter(
            doctor=report_doctor,
            scheduled_time__isnull=False,
        )
        if status and status_field:
            firsts_base = firsts_base.filter(**{status_field: status})

        firsts = firsts_base.values("patient_id").annotate(first_dt=Min("scheduled_time"))
        new_patients = firsts.filter(first_dt__gte=start_dt, first_dt__lte=end_dt).count()
        returning_patients = max(unique_patients - new_patients, 0)
    except Exception:
        logger.exception("Failed to calculate new/returning patients for doctor reports.")
        new_patients = 0
        returning_patients = 0

    summary = {
        "total": total,
        "completed": completed,
        "revenue": revenue,
        "unique_patients": unique_patients,
        "completion_rate": completion_rate,
        "new_patients": new_patients,
        "returning_patients": returning_patients,
    }

    # Status breakdown chart data
    # Provide a consistent shape for JS:
    # {labels: [...], data: [...]}
    statuses = ["completed", "pending", "cancelled"]
    status_counts = {s: 0 for s in statuses}

    if status_field:
        try:
            rows = qs.values(status_field).annotate(c=Count("id"))
            for r in rows:
                k = (r.get(status_field) or "").lower()
                if k in status_counts:
                    status_counts[k] = int(r.get("c") or 0)
        except Exception:
            logger.exception("Failed to build status breakdown for doctor reports.")
    else:
        # If no status field, treat all as "pending"
        status_counts["pending"] = total

    status_breakdown = {
        "labels": ["Completed", "Pending", "Cancelled"],
        "data": [status_counts["completed"], status_counts["pending"], status_counts["cancelled"]],
    }

    # Daily chart data
    # Provide:
    # {labels: ['2026-02-01', ...], appointments: [..], revenue: [..]}
    daily_labels: list[str] = []
    daily_counts: list[int] = []
    daily_revenue: list[int] = []

    try:
        daily_base = qs.annotate(day=TruncDate("scheduled_time")).values("day")
        if has_money:
            daily_qs = daily_base.annotate(
                count=Count("id"),
                revenue=Sum("iqd_amount"),
            ).order_by("day")
        else:
            daily_qs = daily_base.annotate(
                count=Count("id"),
            ).order_by("day")

        for r in daily_qs:
            d = r.get("day")
            if isinstance(d, date):
                daily_labels.append(d.isoformat())
            else:
                daily_labels.append(str(d or ""))

            daily_counts.append(int(r.get("count") or 0))

            if has_money:
                try:
                    daily_revenue.append(int(r.get("revenue") or 0))
                except Exception:
                    daily_revenue.append(0)
            else:
                daily_revenue.append(0)
    except Exception:
        logger.exception("Failed to build daily chart data for doctor reports.")

    daily = {
        "labels": daily_labels,
        "appointments": daily_counts,
        "revenue": daily_revenue,
    }

    # Monthly chart data (only if has_money)
    monthly = None
    if has_money:
        m_labels: list[str] = []
        m_revenue: list[int] = []
        try:
            m_qs = (
                qs.annotate(m=TruncMonth("scheduled_time"))
                .values("m")
                .annotate(
                    revenue=Sum("iqd_amount"),
                    count=Count("id"),
                )
                .order_by("m")
            )
            for r in m_qs:
                m = r.get("m")
                if isinstance(m, datetime):
                    m_labels.append(m.strftime("%Y-%m"))
                else:
                    m_labels.append(str(m or ""))
                try:
                    m_revenue.append(int(r.get("revenue") or 0))
                except Exception:
                    m_revenue.append(0)
        except Exception:
            logger.exception("Failed to build monthly chart data for doctor reports.")

        monthly = {
            "labels": m_labels,
            "revenue": m_revenue,
        }

    # Peak hours
    best_hour_visits = None
    best_hour_revenue = None

    try:
        hour_rows = (
            qs.annotate(h=ExtractHour("scheduled_time"))
            .values("h")
            .annotate(count=Count("id"))
            .order_by("-count")
        )
        top = hour_rows.first()
        if top and top.get("h") is not None:
            best_hour_visits = {
                "hour": f"{int(top['h']):02d}:00",
                "count": int(top.get("count") or 0),
            }
    except Exception:
        logger.exception("Failed to calculate peak visit hour for doctor reports.")
        best_hour_visits = None

    if has_money:
        try:
            hr_rows = (
                qs.annotate(h=ExtractHour("scheduled_time"))
                .values("h")
                .annotate(revenue=Sum("iqd_amount"))
                .order_by("-revenue")
            )
            top = hr_rows.first()
            if top and top.get("h") is not None:
                best_hour_revenue = {
                    "hour": f"{int(top['h']):02d}:00",
                    "revenue": int(top.get("revenue") or 0),
                }
        except Exception:
            logger.exception("Failed to calculate peak revenue hour for doctor reports.")
            best_hour_revenue = None

    # Context for template
    ctx: dict[str, Any] = {
        # Flags
        "has_weasy": HAS_WEASY,
        "has_xlsx": HAS_XLSX,
        "has_money": has_money,
        "has_expenses": HAS_EXPENSES,

        # Doctor selection
        "report_doctor": report_doctor,
        "doctors": doctors_list,  # template uses `{% if doctors %}`
        "selected_doctor_id": selected_doctor_id,

        # Filters
        "period": period,
        "status": status,
        "month": month_sel,
        "year": year_sel,
        "start": start_date,
        "end": end_date,
        "per_page": per_page,
        "month_choices": _month_choices(),

        # Table + pagination
        # HTML: appointments=Page object, page_obj=Page object
        # PDF : appointments=QuerySet (all rows), page_obj=None
        "appointments": appointments_for_template,
        "page_obj": page_obj,

        # Metrics / charts
        "summary": summary,
        "status_breakdown": status_breakdown,
        "daily": daily,
        "monthly": monthly if has_money else None,
        "best_hour_visits": best_hour_visits,
        "best_hour_revenue": best_hour_revenue,
    }

    return ctx