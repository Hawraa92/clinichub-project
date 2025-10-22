# doctor/views.py
from __future__ import annotations

import csv
import json
from datetime import date, datetime, timedelta
from functools import wraps
from io import BytesIO, StringIO
from typing import Iterable, Tuple
from urllib.parse import urlencode
from decimal import Decimal  # ★ NEW

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, FieldDoesNotExist
from django.core.paginator import Paginator
from django.db.models import (
    Count,
    Q,
    Sum,
    Min,
    Case,
    When,
    IntegerField,
    DecimalField,   # ★ NEW
    Value,          # ★ NEW
)
from django.db.models.functions import TruncDate, Coalesce
from django.http import Http404, HttpResponse, HttpResponseRedirect
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone
from django.utils.timezone import make_aware, localtime
from django.utils.translation import gettext_lazy as _
from django.views.decorators.http import require_GET

# PDF (اختياري)
try:
    from weasyprint import CSS, HTML
    HAS_WEASY = True
except ImportError:  # pragma: no cover
    HAS_WEASY = False

# XLSX (اختياري)
try:
    import openpyxl
    HAS_XLSX = True
except Exception:
    HAS_XLSX = False

from appointments.models import Appointment
from medical_archive.models import PatientArchive
from patient.models import Patient
from prescription.models import Prescription
from .models import Doctor

User = get_user_model()


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def has_field(model, name: str) -> bool:
    try:
        model._meta.get_field(name)
        return True
    except FieldDoesNotExist:
        return False


def get_doctor_for_user(user) -> Doctor | None:
    """Return the Doctor instance attached to a user (or None)."""
    return Doctor.objects.select_related("user").filter(user=user).first()


def roles_allowed(*roles: str):
    """
    Decorator restricting access to specific user roles.
    Superusers bypass the check.
    يدعم user.role وكذلك عضوية المجموعات (Doctors / Secretaries / Patients).
    """
    group_map = {r: r.title() + "s" for r in roles}

    def decorator(view_func):
        @wraps(view_func)
        def _wrapped(request, *args, **kwargs):
            u = request.user
            if u.is_superuser:
                return view_func(request, *args, **kwargs)
            if getattr(u, "role", None) in roles:
                return view_func(request, *args, **kwargs)
            if u.groups.filter(name__in=group_map.values()).exists():
                return view_func(request, *args, **kwargs)
            messages.error(request, _("You do not have permission to access this page."))
            raise PermissionDenied(_("Access denied."))
        return _wrapped
    return decorator


def require_doctor_role(view_func):
    """Shortcut for roles_allowed('doctor')."""
    return roles_allowed("doctor")(view_func)


def _to_datetime(date_str: str | None) -> datetime | None:
    """
    Convert 'YYYY-MM-DD' into an aware datetime (start of day).
    Returns None if parsing fails.
    """
    if not date_str:
        return None
    try:
        naive = datetime.strptime(date_str, "%Y-%m-%d")
    except ValueError:
        return None
    return make_aware(naive)


def _to_datetime_end(date_str: str | None) -> datetime | None:
    """
    Convert 'YYYY-MM-DD' into an aware datetime at 23:59:59.
    """
    dt = _to_datetime(date_str)
    if dt:
        dt = dt.replace(hour=23, minute=59, second=59, microsecond=999999)
    return dt


def _filter_date(qs, field: str, start: datetime | None, end: datetime | None):
    """Apply start/end date filters to QuerySet field."""
    if start:
        qs = qs.filter(**{f"{field}__gte": start})
    if end:
        qs = qs.filter(**{f"{field}__lte": end})
    return qs


def _get_period_dates(period: str, start_str: str | None, end_str: str | None) -> tuple[date, date]:
    """
    Resolve a period ('day'|'week'|'month'|'custom') to (start_date, end_date) inclusive.
    """
    today = timezone.localdate()
    if period == "week":
        start = today - timedelta(days=today.weekday())
        end = start + timedelta(days=6)
    elif period == "month":
        start = today.replace(day=1)
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
# Dashboard
# ------------------------------------------------------------------

@login_required
@require_doctor_role
def doctor_dashboard(request):
    doctor = get_doctor_for_user(request.user)
    if not doctor:
        raise Http404(_("Doctor profile not found."))

    today = timezone.localdate()
    start_week = today - timedelta(days=6)

    recent_archives = (
        PatientArchive.objects.filter(doctor=doctor)
        .select_related("patient")
        .order_by("-created_at")[:5]
    )

    total_archives = PatientArchive.objects.filter(doctor=doctor).count()
    total_prescriptions = Prescription.objects.filter(doctor=doctor).count()
    unique_patients = (
        Appointment.objects.filter(doctor=doctor)
        .values("patient")
        .distinct()
        .count()
    )

    todays_qs = (
        Appointment.objects.filter(doctor=doctor, scheduled_time__date=today)
        .select_related("patient")
        .order_by("scheduled_time")
    )
    patients_today = todays_qs.values("patient").distinct().count()
    new_patients_today = (
        Patient.objects.filter(created_at__date=today, appointments__doctor=doctor)
        .distinct()
        .count()
    )

    week_data = (
        Appointment.objects.filter(
            doctor=doctor, scheduled_time__date__range=(start_week, today)
        )
        .annotate(day=TruncDate("scheduled_time"))
        .values("day")
        .annotate(count=Count("id"))
        .order_by("day")
    )
    week_map = {entry["day"]: entry["count"] for entry in week_data}
    week_labels, week_counts = [], []
    for i in range(7):
        d = start_week + timedelta(days=i)
        week_labels.append(d.strftime("%a"))
        week_counts.append(week_map.get(d, 0))

    context = {
        "doctor": doctor,
        "recent_archives": recent_archives,
        "unique_patients": unique_patients,
        "chart_data_json": json.dumps({"labels": week_labels, "data": week_counts}),
        "today_appointments": todays_qs,
        "stats": {
            "patients_today": patients_today,
            "appointments_today": todays_qs.count(),
            "new_patients_today": new_patients_today,
            "total_archives": total_archives,
            "total_prescriptions": total_prescriptions,
            "prescription_count": total_prescriptions,  # legacy compat
        },
    }
    return render(request, "doctor/doctor_dashboard.html", context)


# ------------------------------------------------------------------
# Doctor Detail
# ------------------------------------------------------------------

@login_required
@require_doctor_role
def doctor_detail(request, pk: int):
    doctor = get_object_or_404(Doctor.objects.select_related("user"), pk=pk)
    return render(request, "doctor/doctor_detail.html", {"doctor": doctor})


# ------------------------------------------------------------------
# Patients List (with embedded search)
# ------------------------------------------------------------------

@login_required
@require_doctor_role
def patients_list(request):
    """عرض المرضى المرتبطين بالطبيب مع بحث ونطاق تاريخ."""
    doctor = get_doctor_for_user(request.user)
    if not doctor:
        raise Http404()

    qs = Patient.objects.filter(appointments__doctor=doctor)

    # بحث بالاسم / ID
    q = request.GET.get("q", "").strip()
    if q:
        if q.isdigit():
            qs = qs.filter(Q(id=int(q)) | Q(full_name__icontains=q))
        else:
            qs = qs.filter(full_name__icontains=q)

    # فلترة بالتاريخ (على مواعيد المريض مع هذا الطبيب)
    date_from = request.GET.get("date_from")
    date_to = request.GET.get("date_to")
    qs = _filter_date(qs, "appointments__scheduled_time", _to_datetime(date_from), _to_datetime_end(date_to))

    patients = qs.select_related("user").distinct().order_by("full_name")

    return render(
        request,
        "doctor/patient_records.html",
        {
            "doctor": doctor,
            "patients": patients,
            "query": q,
            "date_from": date_from or "",
            "date_to": date_to or "",
        },
    )


# ------------------------------------------------------------------
# patient_search (Redirect legacy)
# ------------------------------------------------------------------

@login_required
@require_doctor_role
def patient_search(request):
    base = reverse("doctor:patients_list")
    qs = urlencode({k: v for k, v in request.GET.items() if v})
    return HttpResponseRedirect(f"{base}?{qs}" if qs else base)


# ------------------------------------------------------------------
# report_search (اختيار مريض ثم redirect)
# ------------------------------------------------------------------

@login_required
@require_doctor_role
def report_search(request):
    doctor = get_doctor_for_user(request.user)
    if not doctor:
        raise Http404()

    if request.GET.get("patient"):
        pid = request.GET["patient"]
        extra = {k: v for k, v in request.GET.items() if k in ("date_from", "date_to") and v}
        redirect_url = reverse("doctor:patient_report", args=[pid])
        if extra:
            redirect_url += "?" + urlencode(extra)
        return redirect(redirect_url)

    patients = (
        Patient.objects.filter(appointments__doctor=doctor)
        .select_related("user")
        .distinct()
        .order_by("full_name")
    )
    return render(request, "doctor/patient_search.html", {"doctor": doctor, "patients": patients})


# ------------------------------------------------------------------
# Helper: load report data (per-patient)
# ------------------------------------------------------------------

def _load_report_data(
    doctor: Doctor,
    patient: Patient,
    date_from_str: str | None,
    date_to_str: str | None,
) -> Tuple[Iterable[PatientArchive], Iterable[Prescription], Iterable[Appointment]]:
    df = _to_datetime(date_from_str)
    dt = _to_datetime_end(date_to_str)

    archives = _filter_date(
        PatientArchive.objects.filter(patient=patient, doctor=doctor),
        "created_at", df, dt
    ).order_by("-created_at")

    prescriptions = _filter_date(
        Prescription.objects.filter(doctor=doctor, appointment__patient=patient),
        "date_issued", df, dt
    ).order_by("-date_issued")

    appointments = _filter_date(
        Appointment.objects.filter(patient=patient, doctor=doctor),
        "scheduled_time", df, dt
    ).order_by("-scheduled_time")

    return archives, prescriptions, appointments


# ------------------------------------------------------------------
# Patient Report (HTML)
# ------------------------------------------------------------------

@login_required
@require_doctor_role
def patient_report(request, patient_id: int):
    doctor = get_doctor_for_user(request.user)
    patient = get_object_or_404(Patient, id=patient_id, appointments__doctor=doctor)

    date_from, date_to = request.GET.get("date_from"), request.GET.get("date_to")
    archives, prescriptions, appointments = _load_report_data(doctor, patient, date_from, date_to)

    return render(
        request,
        "doctor/report_patient.html",
        {
            "doctor": doctor,
            "patient": patient,
            "archives": archives.select_related("doctor__user"),
            "prescriptions": prescriptions,
            "appointments": appointments.select_related("doctor__user"),
            "now": timezone.now(),
            "date_from": date_from,
            "date_to": date_to,
            "primary_diagnosis": getattr(patient, "primary_diagnosis", None),
            "chronic_conditions": getattr(patient, "chronic_conditions", []),
        },
    )


# ------------------------------------------------------------------
# Export: PDF & CSV (per-patient)
# ------------------------------------------------------------------

@login_required
@require_doctor_role
@require_GET
def report_pdf(request, patient_id: int):
    if not HAS_WEASY:
        return HttpResponse(_("WeasyPrint is not installed."), status=500)

    doctor = get_doctor_for_user(request.user)
    patient = get_object_or_404(Patient, id=patient_id, appointments__doctor=doctor)

    date_from, date_to = request.GET.get("date_from"), request.GET.get("date_to")
    archives, prescriptions, appointments = _load_report_data(doctor, patient, date_from, date_to)

    html = render_to_string(
        "doctor/report_patient.html",
        {
            "doctor": doctor,
            "patient": patient,
            "archives": archives,
            "prescriptions": prescriptions,
            "appointments": appointments,
            "now": timezone.now(),
            "date_from": date_from,
            "date_to": date_to,
        },
    )

    pdf_buffer = BytesIO()
    HTML(string=html, base_url=request.build_absolute_uri("/")).write_pdf(
        pdf_buffer,
        stylesheets=[CSS(string="@page { size: A4; margin: 1.5cm }")],
    )
    response = HttpResponse(pdf_buffer.getvalue(), content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="patient_{patient_id}_report.pdf"'
    return response


@login_required
@require_doctor_role
@require_GET
def report_csv(request, patient_id: int):
    doctor = get_doctor_for_user(request.user)
    patient = get_object_or_404(Patient, id=patient_id, appointments__doctor=doctor)

    date_from, date_to = request.GET.get("date_from"), request.GET.get("date_to")
    archives, prescriptions, appointments = _load_report_data(doctor, patient, date_from, date_to)

    buf = StringIO()
    writer = csv.writer(buf)
    writer.writerow(["Section", "Date", "Patient Name", "Doctor", "Details"])

    for a in archives:
        writer.writerow([
            "Archive",
            a.created_at.isoformat(),
            patient.full_name,
            doctor.user.get_full_name(),
            a.title or a.summary or a.notes or "",
        ])

    for p in prescriptions:
        d = getattr(p, "date_issued", getattr(p, "created_at", None))
        meds = getattr(p, "medications", getattr(p, "instructions", ""))
        writer.writerow([
            "Prescription",
            d.isoformat() if d else "",
            patient.full_name,
            doctor.user.get_full_name(),
            meds,
        ])

    for ap in appointments:
        writer.writerow([
            "Appointment",
            ap.scheduled_time.isoformat(),
            patient.full_name,
            doctor.user.get_full_name(),
            ap.get_status_display(),
        ])

    response = HttpResponse(buf.getvalue(), content_type="text/csv")
    response["Content-Disposition"] = f'attachment; filename="patient_{patient_id}_report.csv"'
    return response


# ------------------------------------------------------------------
# Doctor Reports (حسابات حقيقية للطبيب الحالي)
# ------------------------------------------------------------------

@login_required
@require_doctor_role
def doctor_reports(request):
    """
    صفحة تقارير الطبيب: KPIs + ترند يومي + توزيع الحالات + جدول المواعيد.
    يعتمد على الفترة: period = day|week|month|custom + (start,end اختيارية)
    وفلتر status اختياري (completed|pending|cancelled).
    """
    doctor = get_doctor_for_user(request.user)
    if not doctor:
        raise PermissionDenied(_("Only doctors can view this report."))

    period = request.GET.get("period", "day")
    status = (request.GET.get("status") or "").strip()
    start_date, end_date = _get_period_dates(period, request.GET.get("start"), request.GET.get("end"))

    qs = (
        Appointment.objects
        .select_related("patient", "doctor", "doctor__user")
        .filter(doctor=doctor, scheduled_time__date__gte=start_date, scheduled_time__date__lte=end_date)
        .order_by("scheduled_time")
    )

    if status in {"completed", "cancelled", "pending"}:
        qs = qs.filter(status=status)

    # ---- Counters (efficient aggregation) ----
    agg = qs.aggregate(
        total=Count("id"),
        completed=Count("id", filter=Q(status="completed")),
        cancelled=Count("id", filter=Q(status="cancelled")),
        pending=Count("id", filter=Q(status="pending")),
        revenue=Sum("iqd_amount") if has_field(Appointment, "iqd_amount") else None,
    )
    total = agg["total"] or 0
    completed = agg["completed"] or 0
    cancelled = agg["cancelled"] or 0
    pending = agg["pending"] or 0
    revenue = (agg.get("revenue") or 0) if has_field(Appointment, "iqd_amount") else 0

    # ---- New vs Returning ----
    unique_patients = qs.values("patient_id").distinct().count()
    # أول موعد للمريض مع هذا الطبيب يقع ضمن الفترة
    firsts = (
        Appointment.objects.filter(doctor=doctor)
        .values("patient_id")
        .annotate(first_dt=Min("scheduled_time"))
        .filter(first_dt__date__gte=start_date, first_dt__date__lte=end_date)
        .count()
    )
    returning = max(unique_patients - firsts, 0)

    # ---- Daily series (date -> {count, revenue}) ----
    if has_field(Appointment, "iqd_amount"):
        grouped = (
            qs.annotate(d=TruncDate("scheduled_time"))
            .values("d")
            .annotate(
                count=Count("id"),
                # ★ Fix: لا نخلط Decimal مع Integer؛ نحدد output_field ونستخدم قيمة Decimal صفرية
                revenue=Coalesce(
                    Sum("iqd_amount"),
                    Value(Decimal("0.00")),
                    output_field=DecimalField(max_digits=18, decimal_places=2),
                ),
            )
            .order_by("d")
        )
    else:
        grouped = (
            qs.annotate(d=TruncDate("scheduled_time"))
            .values("d")
            .annotate(count=Count("id"))
            .order_by("d")
        )
        for g in grouped:
            g["revenue"] = Decimal("0.00")

    gmap = {row["d"]: {"count": row["count"], "revenue": row["revenue"]} for row in grouped}
    # املئي الفراغات بأيام بدون بيانات (0)
    daily = []
    cur = start_date
    while cur <= end_date:
        v = gmap.get(cur, {"count": 0, "revenue": Decimal("0.00")})
        daily.append({"day": cur.isoformat(), "count": v["count"], "revenue": v["revenue"]})
        cur += timedelta(days=1)

    # ---- Status breakdown dict للـ Doughnut ----
    status_breakdown = {
        "Completed": completed,
        "Pending": pending,
        "Cancelled": cancelled,
    }

    context = {
        "period": period,
        "status": status,
        "start": start_date,
        "end": end_date,
        "appointments": qs,
        "summary": {
            "total": total,
            "completed": completed,
            "cancelled": cancelled,
            "pending": pending,
            "revenue": revenue,
            "new_patients": firsts,
            "returning_patients": returning,
        },
        "daily": daily,
        "status_breakdown": status_breakdown,
    }
    return render(request, "doctor/doctor_reports.html", context)


# ------------------------------------------------------------------
# Doctor Reports Export (CSV / XLSX)
# ------------------------------------------------------------------

@login_required
@require_doctor_role
@require_GET
def doctor_reports_export(request):
    doctor = get_doctor_for_user(request.user)
    if not doctor:
        raise PermissionDenied(_("Only doctors can export this report."))

    fmt = (request.GET.get("format") or "csv").lower()
    period = request.GET.get("period", "day")
    status = (request.GET.get("status") or "").strip()
    start_date, end_date = _get_period_dates(period, request.GET.get("start"), request.GET.get("end"))

    qs = (
        Appointment.objects
        .select_related("patient", "doctor", "doctor__user")
        .filter(doctor=doctor, scheduled_time__date__gte=start_date, scheduled_time__date__lte=end_date)
        .order_by("scheduled_time")
    )
    if status in {"completed", "cancelled", "pending"}:
        qs = qs.filter(status=status)

    if fmt == "xlsx" and HAS_XLSX:
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Doctor Reports"
        ws.append(["ID", "Date", "Time", "Patient", "Status", "IQD"])
        for a in qs:
            dt = localtime(a.scheduled_time)
            ws.append([
                a.id,
                dt.date().isoformat(),
                dt.strftime("%H:%M"),
                a.patient.full_name,
                a.get_status_display(),
                getattr(a, "iqd_amount", 0) or 0,
            ])
        from io import BytesIO
        buf = BytesIO()
        wb.save(buf)
        buf.seek(0)
        resp = HttpResponse(
            buf.getvalue(),
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        resp["Content-Disposition"] = f'attachment; filename="doctor_reports_{start_date}_{end_date}.xlsx"'
        return resp

    # CSV افتراضيًا
    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="doctor_reports_{start_date}_{end_date}.csv"'
    writer = csv.writer(response)
    writer.writerow(["ID", "Date", "Time", "Patient", "Status", "IQD"])
    for a in qs:
        dt = localtime(a.scheduled_time)
        writer.writerow([
            a.id,
            dt.date().isoformat(),
            dt.strftime("%H:%M"),
            a.patient.full_name,
            a.get_status_display(),
            getattr(a, "iqd_amount", 0) or 0,
        ])
    return response


# ------------------------------------------------------------------
# Available Doctors (محسّنة مع فلاتر وترقيم صفحات)
# ------------------------------------------------------------------

@login_required  # احذفي هذا السطر إذا أردتِ الصفحة علنية
@require_GET
def available_doctors_list(request):
    """
    /doctor/available/
    فلاتر: q، specialty، online=1، min_fee، max_fee
    ترتيب: sort = rating | experience | fee
    يدعم حقول specialty أو specialization، و is_available أو available.
    """
    q = (request.GET.get("q") or "").strip()
    specialty = (request.GET.get("specialty") or "").strip()
    sort = (request.GET.get("sort") or "rating").strip()
    online = request.GET.get("online")
    min_fee = request.GET.get("min_fee")
    max_fee = request.GET.get("max_fee")

    qs = Doctor.objects.select_related("user")

    # التوفر (مرن لاسم الحقل)
    if online in ("1", "true", "on", None):  # None = أول زيارة مع خيار مفعّل افتراضياً
        if has_field(Doctor, "is_available"):
            qs = qs.filter(is_available=True)
        elif has_field(Doctor, "available"):
            qs = qs.filter(available=True)

    # البحث بالاسم/التخصص
    if q:
        q_filter = Q(full_name__icontains=q)
        if has_field(Doctor, "specialty"):
            q_filter |= Q(specialty__icontains=q)
        if has_field(Doctor, "specialization"):
            q_filter |= Q(specialization__icontains=q)
        qs = qs.filter(q_filter)

    # فلتر التخصص
    if specialty:
        spec_filter = Q()
        if has_field(Doctor, "specialty"):
            spec_filter |= Q(specialty__iexact=specialty)
        if has_field(Doctor, "specialization"):
            spec_filter |= Q(specialization__iexact=specialty)
        if spec_filter:
            qs = qs.filter(spec_filter)

    # رسوم الكشف
    try:
        if min_fee:
            qs = qs.filter(consultation_fee__gte=int(min_fee))
        if max_fee:
            qs = qs.filter(consultation_fee__lte=int(max_fee))
    except ValueError:
        pass

    # الترتيب
    sort_map = {}
    if has_field(Doctor, "rating"):
        sort_map["rating"] = "-rating"
    if has_field(Doctor, "experience"):
        sort_map["experience"] = "-experience"
    if has_field(Doctor, "consultation_fee"):
        sort_map["fee"] = "consultation_fee"
    order_by = sort_map.get(sort) or "-full_name"
    qs = qs.order_by(order_by, "full_name")

    # قائمة التخصصات للفلاتر
    specialties_qs = []
    if has_field(Doctor, "specialty"):
        specialties_qs += list(Doctor.objects.values_list("specialty", flat=True))
    if has_field(Doctor, "specialization"):
        specialties_qs += list(Doctor.objects.values_list("specialization", flat=True))
    specialties = sorted({s for s in specialties_qs if s})

    # ترقيم الصفحات
    paginator = Paginator(qs, 12)
    page_obj = paginator.get_page(request.GET.get("page"))

    # توحيد خاصية is_available للقالب
    objs = list(page_obj.object_list)
    for d in objs:
        if not hasattr(d, "is_available"):
            setattr(d, "is_available", getattr(d, "available", False))
    page_obj.object_list = objs

    return render(
        request,
        "doctor/available_doctors.html",
        {
            "doctors": page_obj,   # القالب يلف على doctors
            "page_obj": page_obj,  # للصفحات
            "specialties": specialties,
        },
    )
