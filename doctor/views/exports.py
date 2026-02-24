# doctor/views/exports.py
from __future__ import annotations

import csv
import html as html_lib
from datetime import date, datetime
from io import BytesIO
from typing import Any

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, render
from django.template import TemplateDoesNotExist
from django.template.loader import render_to_string
from django.utils import timezone
from django.utils.timezone import localtime, make_aware
from django.utils.translation import gettext_lazy as _
from django.views.decorators.http import require_GET

from appointments.models import Appointment
from medical_archive.models import PatientArchive
from prescription.models import Prescription

# ------------------------------------------------------------------
# IMPORTANT:
# - Keep exports.py focused on exports (PDF/CSV/XLSX) + the /doctor/reports/ page.
# - Analytics context should come from reports.py to avoid circular imports.
# ------------------------------------------------------------------

# Shared helpers from doctor.views package (__init__.py)
from . import (  # noqa: E402
    HAS_WEASY,
    HAS_XLSX,
    _appt_select_related,
    _normalize_date_range_params,
    _first_existing_field,
    _patients_for_doctor_qs,
    _filter_date,
    _user_display_name,
    _patient_display_name,
    _csv_dt,
    get_doctor_for_user,
    require_doctor_role,
    has_field,
    _load_report_data,
    _resolve_report_doctor,
    _get_period_dates,
    _make_dt_start,
    _make_dt_end,
)

# ✅ Reports analytics payload (NEW file: doctor/views/reports.py)
# This feeds doctor_reports.html with: summary, daily, status_breakdown, monthly, etc.
try:
    from .reports import _fallback_doctor_reports_pdf_html, _build_doctor_reports_payload  # type: ignore
except Exception:
    # If reports.py is missing, fall back to a very minimal payload so the page never crashes.
    def _fallback_doctor_reports_pdf_html(ctx: dict[str, Any]) -> str:
        report_doctor = ctx.get("report_doctor")
        start = ctx.get("start")
        end = ctx.get("end")

        def _safe(x: Any) -> str:
            return html_lib.escape(str(x or ""), quote=True)

        doc_name = _safe(_user_display_name(getattr(report_doctor, "user", None))) if report_doctor else "Doctor"
        return f"""
<!doctype html>
<html><head><meta charset="utf-8"><title>Doctor Reports</title></head>
<body style="font-family:Arial,sans-serif">
  <h2>Doctor Reports (Fallback)</h2>
  <p><b>Doctor:</b> {doc_name}</p>
  <p><b>Period:</b> {_safe(start)} → {_safe(end)}</p>
  <p>This is a fallback page. Create doctor/views/reports.py to enable full analytics.</p>
</body></html>
"""

    def _build_doctor_reports_payload(request, for_pdf: bool = False) -> dict[str, Any]:
        report_doctor, doctors_list, selected_doctor_id = _resolve_report_doctor(request)
        today = timezone.localdate()
        return {
            "has_weasy": HAS_WEASY,
            "has_xlsx": HAS_XLSX,
            "has_money": has_field(Appointment, "iqd_amount"),
            "has_expenses": False,
            "report_doctor": report_doctor,
            "doctors": doctors_list,
            "selected_doctor_id": selected_doctor_id,
            "period": "month",
            "status": "",
            "month": str(today.month),
            "year": str(today.year),
            "start": today.replace(day=1),
            "end": today,
            "per_page": 10,
            "appointments": [],
            "page_obj": None,
            "summary": {
                "total": 0,
                "completed": 0,
                "revenue": 0,
                "unique_patients": 0,
                "completion_rate": 0,
                "new_patients": 0,
                "returning_patients": 0,
            },
            "daily": {"labels": [], "appointments": [], "revenue": []},
            "status_breakdown": {"labels": ["Completed", "Pending", "Cancelled"], "data": [0, 0, 0]},
            "monthly": {"labels": [], "revenue": []},
            "best_hour_visits": None,
            "best_hour_revenue": None,
        }


# ------------------------------------------------------------------
# Security / export safety helpers
# ------------------------------------------------------------------
_FORMULA_PREFIXES = ("=", "+", "-", "@")


def _ensure_report_doctor(report_doctor):
    """
    Ensure report_doctor exists before exporting.
    Prevents None.user crashes and ambiguous exports.
    """
    if not report_doctor:
        raise Http404(_("Doctor profile not found."))
    return report_doctor


def _neutralize_spreadsheet_formula(value: Any) -> Any:
    """
    Prevent CSV/XLSX formula injection in spreadsheet apps.
    Only touches strings that begin (after leading spaces) with = + - @
    """
    if not isinstance(value, str):
        return value

    if not value:
        return value

    stripped = value.lstrip()
    if stripped.startswith(_FORMULA_PREFIXES):
        return "'" + value
    return value


def _csv_safe_cell(value: Any) -> Any:
    """
    CSV-safe cell (formula neutralization for strings).
    """
    if value is None:
        return ""
    return _neutralize_spreadsheet_formula(value)


def _csv_safe_row(row: list[Any]) -> list[Any]:
    return [_csv_safe_cell(v) for v in row]


def _xlsx_safe_cell(value: Any) -> Any:
    """
    XLSX-safe cell (formula neutralization for strings).
    Keep numbers as numbers for proper sorting/summing in Excel.
    """
    if value is None:
        return ""
    if isinstance(value, str):
        return _neutralize_spreadsheet_formula(value)
    return value


# ------------------------------------------------------------------
# Local PDF HTML renderer for Patient Report (safe; avoids circular)
# ------------------------------------------------------------------
def _render_patient_report_pdf_html(request, ctx: dict[str, Any]) -> str:
    """
    Render patient report HTML used for PDF.
    Tries templates; if not found, uses a minimal fallback HTML.
    """
    candidates = (
        "doctor/patient_report_pdf.html",
        "doctor/patient_report.html",
        "doctor/patient_report_view.html",
        "doctor/patient_report_detail.html",
        "doctor/report_patient.html",  # موجود عندج غالباً
    )

    for tpl in candidates:
        try:
            return render_to_string(tpl, ctx, request=request)
        except TemplateDoesNotExist:
            continue
        except Exception:
            break

    doctor = ctx.get("doctor")
    patient = ctx.get("patient")
    archives = ctx.get("archives") or []
    prescriptions = ctx.get("prescriptions") or []
    appointments = ctx.get("appointments") or []
    now = ctx.get("now") or timezone.now()

    def _safe(s: Any) -> str:
        return html_lib.escape(str(s or ""), quote=True)

    doc_name = _safe(_user_display_name(getattr(doctor, "user", None))) if doctor else "Doctor"
    pat_name = _safe(_patient_display_name(patient)) if patient else "Patient"

    html = f"""
<!doctype html>
<html>
<head>
  <meta charset="utf-8" />
  <title>Patient Report</title>
  <style>
    body {{ font-family: Arial, sans-serif; font-size: 12px; }}
    h1 {{ font-size: 18px; margin: 0 0 10px; }}
    h2 {{ font-size: 14px; margin: 18px 0 8px; }}
    .meta {{ color: #555; margin-bottom: 10px; }}
    table {{ width: 100%; border-collapse: collapse; }}
    th, td {{ border: 1px solid #ccc; padding: 6px; vertical-align: top; }}
    th {{ background: #f3f3f3; }}
  </style>
</head>
<body>
  <h1>Patient Report</h1>
  <div class="meta">
    <div><b>Doctor:</b> {doc_name}</div>
    <div><b>Patient:</b> {pat_name}</div>
    <div><b>Generated:</b> {_safe(now)}</div>
  </div>

  <h2>Archives</h2>
  <table>
    <tr><th>#</th><th>Title</th><th>Date</th><th>Notes</th></tr>
"""
    arch_date_field = _first_existing_field(PatientArchive, ("created_at", "created_on", "date", "created")) or "id"
    for i, a in enumerate(archives, start=1):
        title = getattr(a, "title", "") or getattr(a, "subject", "") or getattr(a, "name", "") or "Archive"
        dtv = getattr(a, arch_date_field, None)
        notes = (
            getattr(a, "notes", "")
            or getattr(a, "summary", "")
            or getattr(a, "details", "")
            or getattr(a, "content", "")
            or getattr(a, "description", "")
            or ""
        )
        html += f"<tr><td>{i}</td><td>{_safe(title)}</td><td>{_safe(_csv_dt(dtv))}</td><td>{_safe(notes)}</td></tr>"

    html += """
  </table>

  <h2>Prescriptions</h2>
  <table>
    <tr><th>#</th><th>ID</th><th>Date</th><th>Details</th></tr>
"""
    presc_date_field = _first_existing_field(Prescription, ("date_issued", "issued_at", "created_at", "date")) or "id"
    for i, p in enumerate(prescriptions, start=1):
        dtv = getattr(p, presc_date_field, None)
        meds = getattr(p, "medications", None)
        if meds is None:
            meds = getattr(p, "instructions", "") or getattr(p, "note", "") or ""
        html += f"<tr><td>{i}</td><td>{_safe(getattr(p, 'pk', ''))}</td><td>{_safe(_csv_dt(dtv))}</td><td>{_safe(meds)}</td></tr>"

    html += """
  </table>

  <h2>Appointments</h2>
  <table>
    <tr><th>#</th><th>ID</th><th>Scheduled</th><th>Status</th></tr>
"""
    for i, ap in enumerate(appointments, start=1):
        st = getattr(ap, "scheduled_time", None)
        status_text = ap.get_status_display() if hasattr(ap, "get_status_display") else getattr(ap, "status", "")
        html += f"<tr><td>{i}</td><td>{_safe(getattr(ap, 'pk', ''))}</td><td>{_safe(_csv_dt(st))}</td><td>{_safe(status_text)}</td></tr>"

    html += """
  </table>
</body>
</html>
"""
    return html


# ------------------------------------------------------------------
# ✅ MAIN Doctor Reports page (HTML) — used by views/__init__.py wrapper
# ------------------------------------------------------------------
@login_required
@require_doctor_role
@require_GET
def doctor_reports(request):
    """
    HTML page for Reports & Analytics button: /doctor/reports/
    Uses reports.py payload to feed doctor_reports.html
    """
    ctx = _build_doctor_reports_payload(request, for_pdf=False)

    try:
        return render(request, "doctor/doctor_reports.html", ctx)
    except TemplateDoesNotExist:
        return HttpResponse(_fallback_doctor_reports_pdf_html(ctx))


# ------------------------------------------------------------------
# Patient report exports
# ------------------------------------------------------------------
@login_required
@require_doctor_role
@require_GET
def report_pdf(request, patient_id: int):
    if not HAS_WEASY:
        return HttpResponse(_("WeasyPrint is not installed."), status=501)

    from weasyprint import CSS, HTML  # type: ignore

    doctor = get_doctor_for_user(request.user)
    if not doctor:
        raise Http404()

    patient = get_object_or_404(_patients_for_doctor_qs(doctor), id=patient_id)

    df_str, dt_str, _df, _dt, _swapped, _inv_f, _inv_t = _normalize_date_range_params(
        request.GET.get("date_from"),
        request.GET.get("date_to"),
    )

    archives, prescriptions, appointments = _load_report_data(doctor, patient, df_str, dt_str)

    ctx = {
        "doctor": doctor,
        "patient": patient,
        "archives": archives,
        "prescriptions": prescriptions,
        "appointments": appointments,
        "now": timezone.now(),
        "date_from": df_str,
        "date_to": dt_str,
        "is_pdf": True,
    }

    html = _render_patient_report_pdf_html(request, ctx)

    pdf_buffer = BytesIO()
    HTML(string=html, base_url=request.build_absolute_uri("/")).write_pdf(
        pdf_buffer,
        stylesheets=[
            CSS(
                string="""
                @page { size: A4; margin: 1.5cm; }
                .no-print { display: none !important; }
                """
            )
        ],
    )
    response = HttpResponse(pdf_buffer.getvalue(), content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="patient_{patient_id}_report.pdf"'
    return response


@login_required
@require_doctor_role
@require_GET
def report_csv(request, patient_id: int):
    doctor = get_doctor_for_user(request.user)
    if not doctor:
        raise Http404()

    patient = get_object_or_404(_patients_for_doctor_qs(doctor), id=patient_id)

    df_str, dt_str, _df, _dt, _swapped, _inv_f, _inv_t = _normalize_date_range_params(
        request.GET.get("date_from"),
        request.GET.get("date_to"),
    )

    archives, prescriptions, appointments = _load_report_data(doctor, patient, df_str, dt_str)

    presc_date_field = _first_existing_field(Prescription, ("date_issued", "issued_at", "created_at", "date"))
    arch_date_field = _first_existing_field(PatientArchive, ("created_at", "created_on", "date", "created"))

    mode = (request.GET.get("mode") or "simple").strip().lower()
    if mode not in {"simple", "full"}:
        mode = "simple"

    def _clean_cell(v: Any) -> str:
        s = str(v or "")
        s = s.replace("\r", " ").replace("\n", " ").replace("\t", " ")
        return " ".join(s.split())

    def _clean_export_text(v: Any) -> str:
        return str(_csv_safe_cell(_clean_cell(v)))

    def _as_sort_dt(v) -> datetime | None:
        if not v:
            return None
        if isinstance(v, datetime):
            dtv = v
        elif isinstance(v, date):
            dtv = datetime.combine(v, datetime.min.time())
        else:
            return None
        try:
            if settings.USE_TZ and timezone.is_naive(dtv):
                dtv = make_aware(dtv, timezone.get_current_timezone())
        except Exception:
            pass
        try:
            if settings.USE_TZ:
                dtv = localtime(dtv)
        except Exception:
            pass
        return dtv

    patient_name = _clean_export_text(_patient_display_name(patient))
    doctor_name = _clean_export_text(_user_display_name(getattr(doctor, "user", None)))
    doctor_id = getattr(doctor, "pk", "")

    has_money = has_field(Appointment, "iqd_amount")
    has_queue = has_field(Appointment, "queue_number")

    response = HttpResponse(content_type="text/csv; charset=utf-8")
    fname = f"patient_{patient_id}_report.csv" if mode == "simple" else f"patient_{patient_id}_report_full.csv"
    response["Content-Disposition"] = f'attachment; filename="{fname}"'
    response.write("\ufeff")

    writer = csv.writer(response)

    if mode == "simple":
        writer.writerow(["Section", "Date", "Patient Name", "Doctor", "Details"])

        for a in archives:
            d = getattr(a, arch_date_field, None) if arch_date_field else getattr(a, "created_at", None)
            a_doc = getattr(a, "doctor", None)
            a_doc_name_raw = _user_display_name(getattr(a_doc, "user", None)) if a_doc else doctor_name
            details = (
                getattr(a, "title", "")
                or getattr(a, "summary", "")
                or getattr(a, "notes", "")
                or getattr(a, "diagnosis", "")
                or ""
            )
            writer.writerow(
                _csv_safe_row(
                    [
                        "Archive",
                        _csv_dt(d),
                        patient_name,
                        _clean_export_text(a_doc_name_raw),
                        _clean_export_text(details),
                    ]
                )
            )

        for p in prescriptions:
            d = getattr(p, presc_date_field, None) if presc_date_field else getattr(p, "created_at", None)
            p_doc = getattr(p, "doctor", None)
            p_doc_name_raw = _user_display_name(getattr(p_doc, "user", None)) if p_doc else doctor_name
            meds = getattr(p, "medications", None)
            if meds is None:
                meds = getattr(p, "instructions", "") or getattr(p, "note", "") or ""
            writer.writerow(
                _csv_safe_row(
                    [
                        "Prescription",
                        _csv_dt(d),
                        patient_name,
                        _clean_export_text(p_doc_name_raw),
                        _clean_export_text(meds),
                    ]
                )
            )

        for ap in appointments:
            st = getattr(ap, "scheduled_time", None)
            ap_doc = getattr(ap, "doctor", None)
            ap_doc_name_raw = _user_display_name(getattr(ap_doc, "user", None)) if ap_doc else doctor_name
            status_text = ap.get_status_display() if hasattr(ap, "get_status_display") else getattr(ap, "status", "")
            writer.writerow(
                _csv_safe_row(
                    [
                        "Appointment",
                        _csv_dt(st),
                        patient_name,
                        _clean_export_text(ap_doc_name_raw),
                        _clean_export_text(status_text),
                    ]
                )
            )

        return response

    writer.writerow(
        [
            "Section",
            "Section ID",
            "Record ID",
            "Patient ID",
            "Patient Name",
            "Doctor ID",
            "Doctor",
            "DateTime",
            "Date",
            "Time",
            "Status",
            "Queue #",
            "IQD",
            "Details",
        ]
    )

    rows: list[dict[str, Any]] = []

    for a in archives:
        raw_dt = getattr(a, arch_date_field, None) if arch_date_field else getattr(a, "created_at", None)
        dtv = _as_sort_dt(raw_dt)

        a_doc = getattr(a, "doctor", None)
        a_doc_user = getattr(a_doc, "user", None) if a_doc else None
        a_doc_name = _user_display_name(a_doc_user) if a_doc else doctor_name
        a_doc_id = getattr(a_doc, "pk", doctor_id) if a_doc else doctor_id

        details = (
            getattr(a, "title", "")
            or getattr(a, "summary", "")
            or getattr(a, "notes", "")
            or getattr(a, "diagnosis", "")
            or ""
        )

        rows.append(
            {
                "section": "Archive",
                "section_id": "archive",
                "record_id": getattr(a, "pk", ""),
                "patient_id": getattr(patient, "pk", ""),
                "patient_name": patient_name,
                "doctor_id": a_doc_id,
                "doctor_name": _clean_export_text(a_doc_name),
                "dt": dtv,
                "status": "",
                "queue": "",
                "iqd": "",
                "details": _clean_export_text(details),
            }
        )

    for p in prescriptions:
        raw_dt = getattr(p, presc_date_field, None) if presc_date_field else getattr(p, "created_at", None)
        dtv = _as_sort_dt(raw_dt)

        p_doc = getattr(p, "doctor", None)
        p_doc_user = getattr(p_doc, "user", None) if p_doc else None
        p_doc_name = _user_display_name(p_doc_user) if p_doc else doctor_name
        p_doc_id = getattr(p_doc, "pk", doctor_id) if p_doc else doctor_id

        meds = getattr(p, "medications", None)
        if meds is None:
            meds = getattr(p, "instructions", "") or getattr(p, "note", "") or ""

        rows.append(
            {
                "section": "Prescription",
                "section_id": "prescription",
                "record_id": getattr(p, "pk", ""),
                "patient_id": getattr(patient, "pk", ""),
                "patient_name": patient_name,
                "doctor_id": p_doc_id,
                "doctor_name": _clean_export_text(p_doc_name),
                "dt": dtv,
                "status": "",
                "queue": "",
                "iqd": "",
                "details": _clean_export_text(meds),
            }
        )

    for ap in appointments:
        dtv = _as_sort_dt(getattr(ap, "scheduled_time", None))
        ap_doc = getattr(ap, "doctor", None)
        ap_doc_user = getattr(ap_doc, "user", None) if ap_doc else None
        ap_doc_name = _user_display_name(ap_doc_user) if ap_doc else doctor_name
        ap_doc_id = getattr(ap_doc, "pk", doctor_id) if ap_doc else doctor_id

        status_text = ap.get_status_display() if hasattr(ap, "get_status_display") else getattr(ap, "status", "")
        queue_val = getattr(ap, "queue_number", "") if has_queue else ""
        iqd_val = getattr(ap, "iqd_amount", "") if has_money else ""

        rows.append(
            {
                "section": "Appointment",
                "section_id": "appointment",
                "record_id": getattr(ap, "pk", ""),
                "patient_id": getattr(patient, "pk", ""),
                "patient_name": patient_name,
                "doctor_id": ap_doc_id,
                "doctor_name": _clean_export_text(ap_doc_name),
                "dt": dtv,
                "status": _clean_export_text(status_text),
                "queue": queue_val,
                "iqd": iqd_val,
                "details": _clean_export_text(status_text),
            }
        )

    def _sort_key(r: dict[str, Any]):
        dtv2 = r.get("dt")
        if isinstance(dtv2, datetime):
            try:
                if settings.USE_TZ and timezone.is_naive(dtv2):
                    dtv2 = make_aware(dtv2, timezone.get_current_timezone())
            except Exception:
                pass
            return dtv2
        return datetime.min.replace(tzinfo=timezone.get_current_timezone()) if settings.USE_TZ else datetime.min

    rows.sort(key=_sort_key, reverse=True)

    for r in rows:
        dtv2 = r.get("dt")
        dt_str = _csv_dt(dtv2) if dtv2 else ""
        d_str, t_str = "", ""
        if isinstance(dtv2, datetime):
            try:
                d_str = dtv2.date().isoformat()
                t_str = dtv2.strftime("%H:%M")
            except Exception:
                d_str, t_str = "", ""

        writer.writerow(
            _csv_safe_row(
                [
                    r.get("section", ""),
                    r.get("section_id", ""),
                    r.get("record_id", ""),
                    r.get("patient_id", ""),
                    r.get("patient_name", ""),
                    r.get("doctor_id", ""),
                    r.get("doctor_name", ""),
                    dt_str,
                    d_str,
                    t_str,
                    r.get("status", ""),
                    r.get("queue", ""),
                    r.get("iqd", ""),
                    r.get("details", ""),
                ]
            )
        )

    return response


# ------------------------------------------------------------------
# Doctor reports exports (PDF)
# ------------------------------------------------------------------
@login_required
@require_doctor_role
@require_GET
def doctor_reports_pdf(request):
    if not HAS_WEASY:
        return HttpResponse(_("WeasyPrint is not installed."), status=501)

    from weasyprint import CSS, HTML  # type: ignore

    ctx = _build_doctor_reports_payload(request, for_pdf=True)

    report_doctor = _ensure_report_doctor(ctx.get("report_doctor"))

    try:
        html = render_to_string("doctor/doctor_reports_pdf.html", ctx, request=request)
    except TemplateDoesNotExist:
        html = _fallback_doctor_reports_pdf_html(ctx)

    pdf_bytes = HTML(string=html, base_url=request.build_absolute_uri("/")).write_pdf(
        stylesheets=[CSS(string="@page { size: A4; margin: 1.2cm; }")]
    )

    start_date = ctx.get("start")
    end_date = ctx.get("end")

    resp = HttpResponse(pdf_bytes, content_type="application/pdf")
    doc_id = getattr(report_doctor, "pk", "doctor")
    resp["Content-Disposition"] = f'attachment; filename="doctor_{doc_id}_reports_{start_date}_{end_date}.pdf"'
    return resp


# ------------------------------------------------------------------
# Doctor reports export (CSV/XLSX)
# ------------------------------------------------------------------
@login_required
@require_doctor_role
@require_GET
def doctor_reports_export(request):
    report_doctor, _doctors_list, _selected_doctor_id = _resolve_report_doctor(request)
    report_doctor = _ensure_report_doctor(report_doctor)

    fmt = (request.GET.get("format") or "csv").strip().lower()
    if fmt not in {"csv", "xlsx"}:
        fmt = "csv"

    period = (request.GET.get("period") or "month").strip().lower()
    if period not in {"day", "week", "month", "year", "custom"}:
        period = "month"

    status_field = "status" if has_field(Appointment, "status") else None
    status = (request.GET.get("status") or "").strip().lower()
    if status not in {"completed", "pending", "cancelled"}:
        status = ""

    month_sel = (request.GET.get("month") or "").strip()
    year_sel = (request.GET.get("year") or "").strip()

    start_date, end_date = _get_period_dates(
        period,
        request.GET.get("start"),
        request.GET.get("end"),
        month_str=month_sel or None,
        year_str=year_sel or None,
    )
    start_dt = _make_dt_start(start_date)
    end_dt = _make_dt_end(end_date)

    qs = Appointment.objects.filter(doctor=report_doctor, scheduled_time__isnull=False).order_by("scheduled_time")
    qs = _appt_select_related(qs)
    qs = _filter_date(qs, "scheduled_time", start_dt, end_dt)

    if status and status_field:
        qs = qs.filter(**{status_field: status})

    has_money = has_field(Appointment, "iqd_amount")

    doctor_display = _user_display_name(getattr(report_doctor, "user", None))

    if fmt == "xlsx":
        if not HAS_XLSX:
            return HttpResponse(_("XLSX export requires openpyxl. Install it or use CSV."), status=501)

        import openpyxl  # type: ignore

        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Doctor Reports"
        ws.append(["Doctor", "ID", "Date", "Time", "Patient", "Status", "IQD"])

        for a in qs:
            try:
                dtv = localtime(a.scheduled_time) if (settings.USE_TZ and a.scheduled_time) else a.scheduled_time
            except Exception:
                dtv = a.scheduled_time

            d_str = dtv.date().isoformat() if isinstance(dtv, datetime) else ""
            t_str = dtv.strftime("%H:%M") if isinstance(dtv, datetime) else ""

            status_label = (
                a.get_status_display()
                if hasattr(a, "get_status_display")
                else (getattr(a, status_field, "") if status_field else "")
            )

            ws.append(
                [
                    _xlsx_safe_cell(doctor_display),
                    a.id,
                    _xlsx_safe_cell(d_str),
                    _xlsx_safe_cell(t_str),
                    _xlsx_safe_cell(_patient_display_name(getattr(a, "patient", None))),
                    _xlsx_safe_cell(status_label),
                    (getattr(a, "iqd_amount", 0) or 0) if has_money else 0,
                ]
            )

        buf = BytesIO()
        wb.save(buf)
        buf.seek(0)

        resp = HttpResponse(
            buf.getvalue(),
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        resp["Content-Disposition"] = f'attachment; filename="doctor_{report_doctor.pk}_reports_{start_date}_{end_date}.xlsx"'
        return resp

    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="doctor_{report_doctor.pk}_reports_{start_date}_{end_date}.csv"'
    response.write("\ufeff")

    writer = csv.writer(response)
    writer.writerow(["Doctor", "ID", "Date", "Time", "Patient", "Status", "IQD"])

    for a in qs:
        try:
            dtv = localtime(a.scheduled_time) if (settings.USE_TZ and a.scheduled_time) else a.scheduled_time
        except Exception:
            dtv = a.scheduled_time

        d_str = dtv.date().isoformat() if isinstance(dtv, datetime) else ""
        t_str = dtv.strftime("%H:%M") if isinstance(dtv, datetime) else ""

        status_label = (
            a.get_status_display()
            if hasattr(a, "get_status_display")
            else (getattr(a, status_field, "") if status_field else "")
        )

        writer.writerow(
            _csv_safe_row(
                [
                    doctor_display,
                    a.id,
                    d_str,
                    t_str,
                    _patient_display_name(getattr(a, "patient", None)),
                    status_label,
                    (getattr(a, "iqd_amount", 0) or 0) if has_money else 0,
                ]
            )
        )

    return response