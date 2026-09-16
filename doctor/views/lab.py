from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect
from django.utils.translation import gettext_lazy as _

from patient.models import Patient

# نستخدم الأدوات المساعدة من __init__.py مؤقتاً حتى ما ينكسر شي
from . import (
    _filter_date,
    _get_page_size,
    _lab_date_field,
    _lab_doctor_filter,
    _lab_patient_field,
    _lab_stats_for_doctor,
    _lab_status_field,
    _normalize_date_range_params,
    _render_or_fallback,
    _resolve_lab_models,
    _reverse_any,
    _is_our_laborder_model,
    get_doctor_for_user,
    has_field,
    require_doctor_role,
)


# ------------------------------------------------------------------
# ✅ Lab (Doctor side) - list + detail
# ------------------------------------------------------------------
@login_required
@require_doctor_role
def doctor_lab_requests(request):
    doctor = get_doctor_for_user(request.user)
    if not doctor:
        raise Http404(_("Doctor profile not found."))

    req_model, _ = _resolve_lab_models()
    if not req_model:
        messages.info(request, _("Lab module is not installed yet."))
        return redirect(_reverse_any("doctor:dashboard"))

    qs = _lab_doctor_filter(req_model.objects.all(), doctor)

    status_filter = (request.GET.get("status") or "").strip().lower()
    q = (request.GET.get("q") or "").strip()

    status_f = _lab_status_field()
    date_f = _lab_date_field()
    patient_f = _lab_patient_field()

    if status_f:
        try:
            if _is_our_laborder_model() and status_f == "status":
                if status_filter == "completed":
                    qs = qs.filter(status__in=["READY", "SENT", "APPROVED", "COMPLETED", "DONE", "VERIFIED"])
                elif status_filter == "pending":
                    qs = qs.filter(status__in=["PENDING", "IN_PROGRESS"])
            else:
                completed_q = (
                    Q(**{f"{status_f}__iexact": "completed"})
                    | Q(**{f"{status_f}__iexact": "done"})
                    | Q(**{f"{status_f}__iexact": "ready"})
                    | Q(**{f"{status_f}__iexact": "sent"})
                    | Q(**{f"{status_f}__iexact": "approved"})
                    | Q(**{f"{status_f}__iexact": "finished"})
                    | Q(**{f"{status_f}__iexact": "verified"})
                )
                if status_filter == "completed":
                    qs = qs.filter(completed_q)
                elif status_filter == "pending":
                    qs = qs.exclude(completed_q)
        except Exception:
            pass

    if q and patient_f:
        try:
            look = Q()
            if q.isdigit():
                look |= Q(**{f"{patient_f}__id": int(q)})
            if has_field(Patient, "full_name"):
                look |= Q(**{f"{patient_f}__full_name__icontains": q})
            if has_field(Patient, "name"):
                look |= Q(**{f"{patient_f}__name__icontains": q})
            if look:
                qs = qs.filter(look)
        except Exception:
            pass

    df_str, dt_str, df_dt, dt_dt, _swapped, _invalid_from, _invalid_to = _normalize_date_range_params(
        request.GET.get("date_from"),
        request.GET.get("date_to"),
    )
    if date_f and (df_dt or dt_dt):
        try:
            qs = _filter_date(qs, date_f, df_dt, dt_dt)
        except Exception:
            pass

    if date_f:
        try:
            qs = qs.order_by(f"-{date_f}")
        except Exception:
            qs = qs.order_by("-id")
    else:
        qs = qs.order_by("-id")

    per_page = _get_page_size(request, default=10)
    paginator = Paginator(qs, per_page)
    page_obj = paginator.get_page(request.GET.get("page"))

    context = {
        "doctor": doctor,
        "requests": page_obj,
        "orders": page_obj,
        "items": page_obj,
        "page_obj": page_obj,
        "per_page": per_page,
        "q": q,
        "status": status_filter,
        "date_from": df_str or "",
        "date_to": dt_str or "",
        "lab_stats": _lab_stats_for_doctor(doctor),
        "has_lab": True,
    }

    template_candidates = [
        "doctor/lab/doctor_requests.html",
        "lab/doctor_requests.html",
        "lab/lab_inbox.html",
        "lab/lab_dashboard.html",
        "lab/doctor_create_order.html",
    ]
    return _render_or_fallback(request, template_candidates, context, "Lab Requests")


@login_required
@require_doctor_role
def doctor_lab_request_detail(request, request_id: int):
    doctor = get_doctor_for_user(request.user)
    if not doctor:
        raise Http404(_("Doctor profile not found."))

    req_model, res_model = _resolve_lab_models()
    if not req_model:
        raise Http404(_("Lab module is not installed."))

    qs = _lab_doctor_filter(req_model.objects.all(), doctor)
    obj = get_object_or_404(qs, pk=request_id)

    result_obj = None
    if res_model:
        for rel in ("lab_request", "request", "order", "test_request"):
            if has_field(res_model, rel):
                try:
                    result_obj = res_model.objects.filter(**{rel: obj}).order_by("-id").first()
                    break
                except Exception:
                    continue

    context = {
        "doctor": doctor,
        "request_obj": obj,
        "order_obj": obj,
        "order": obj,
        "lab_order": obj,
        "lab_request": obj,
        "result_obj": result_obj,
        "lab_stats": _lab_stats_for_doctor(doctor),
        "has_lab": True,
    }

    template_candidates = [
        "doctor/lab/doctor_request_detail.html",
        "lab/doctor_order_detail.html",
        "lab/lab_order_detail.html",
    ]
    return _render_or_fallback(request, template_candidates, context, "Lab Request Detail")
