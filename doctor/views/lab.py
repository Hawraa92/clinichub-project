from __future__ import annotations

import logging
from typing import Any

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Q, QuerySet
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

logger = logging.getLogger(__name__)


# ------------------------------------------------------------------
# Internal helpers
# ------------------------------------------------------------------
_COMPLETED_STATUS_ALIASES = (
    "completed",
    "done",
    "ready",
    "sent",
    "approved",
    "finished",
    "verified",
)

_NON_PENDING_TERMINAL_ALIASES = (
    "cancelled",
    "canceled",
    "rejected",
    "failed",
    "error",
    "invalid",
)

# حالات شائعة للحالات الجارية/غير المكتملة
_PENDING_STATUS_ALIASES = (
    "pending",
    "in_progress",
    "in-progress",
    "processing",
    "requested",
    "queued",
    "received",
    "sample_collected",
    "collecting",
    "running",
)


def _or_iexact(field_name: str, values: tuple[str, ...]) -> Q:
    q = Q()
    for val in values:
        q |= Q(**{f"{field_name}__iexact": val})
    return q


def _apply_status_filter(qs: QuerySet, *, status_filter: str, status_field: str | None) -> QuerySet:
    """
    Apply robust status filter with best-effort compatibility across lab models.
    """
    if not status_field or not status_filter:
        return qs

    if status_filter not in {"completed", "pending"}:
        return qs

    # ✅ Special handling for your own LabOrder model (common uppercase enum style)
    if _is_our_laborder_model() and status_field == "status":
        try:
            if status_filter == "completed":
                return qs.filter(
                    _or_iexact(
                        "status",
                        ("READY", "SENT", "APPROVED", "COMPLETED", "DONE", "VERIFIED"),
                    )
                )

            # pending = exclude completed + terminal non-pending
            return qs.exclude(
                _or_iexact(
                    "status",
                    ("READY", "SENT", "APPROVED", "COMPLETED", "DONE", "VERIFIED", "CANCELLED", "CANCELED", "REJECTED", "FAILED"),
                )
            )
        except Exception:
            logger.exception("Failed applying status filter on own LabOrder model")
            return qs

    # ✅ Generic fallback for unknown models
    try:
        completed_q = _or_iexact(status_field, _COMPLETED_STATUS_ALIASES)
        terminal_non_pending_q = _or_iexact(status_field, _NON_PENDING_TERMINAL_ALIASES)
        pending_hint_q = _or_iexact(status_field, _PENDING_STATUS_ALIASES)

        if status_filter == "completed":
            return qs.filter(completed_q)

        # pending:
        # 1) prefer explicit pending-like statuses if they exist
        # 2) otherwise fallback to "not completed and not terminal"
        filtered = qs.filter(pending_hint_q)
        try:
            if filtered.exists():
                return filtered
        except Exception:
            # if exists() fails for any backend/model quirk, fallback below
            pass

        return qs.exclude(completed_q | terminal_non_pending_q)

    except Exception:
        logger.exception("Failed applying generic status filter (field=%s)", status_field)
        return qs


def _apply_search_filter(qs: QuerySet, *, q: str, patient_field: str | None) -> QuerySet:
    """
    Search by patient ID / name (best-effort depending on patient fields).
    """
    if not q or not patient_field:
        return qs

    try:
        look = Q()

        if q.isdigit():
            look |= Q(**{f"{patient_field}__id": int(q)})

        if has_field(Patient, "full_name"):
            look |= Q(**{f"{patient_field}__full_name__icontains": q})

        if has_field(Patient, "name"):
            look |= Q(**{f"{patient_field}__name__icontains": q})

        # Optional common fields if present
        if has_field(Patient, "phone"):
            look |= Q(**{f"{patient_field}__phone__icontains": q})

        if has_field(Patient, "email"):
            look |= Q(**{f"{patient_field}__email__icontains": q})

        # Q() الفارغة ما نستخدمها
        if getattr(look, "children", None):
            return qs.filter(look)

    except Exception:
        logger.exception("Failed applying lab search filter (q=%r, patient_field=%s)", q, patient_field)

    return qs


def _apply_date_filter_with_feedback(request, qs: QuerySet, *, date_field: str | None) -> tuple[QuerySet, str, str]:
    """
    Apply date range filter + optional user feedback for invalid/swapped dates.
    Returns (qs, date_from_str, date_to_str)
    """
    df_str, dt_str, df_dt, dt_dt, swapped, invalid_from, invalid_to = _normalize_date_range_params(
        request.GET.get("date_from"),
        request.GET.get("date_to"),
    )

    if swapped:
        messages.info(request, _("Date range was adjusted automatically (from/to were swapped)."))

    if invalid_from or invalid_to:
        messages.warning(request, _("Some date filters were invalid and were ignored."))

    if date_field and (df_dt or dt_dt):
        try:
            qs = _filter_date(qs, date_field, df_dt, dt_dt)
        except Exception:
            logger.exception("Failed applying lab date filter (field=%s)", date_field)

    return qs, (df_str or ""), (dt_str or "")


def _safe_order_lab_qs(qs: QuerySet, *, date_field: str | None) -> QuerySet:
    if date_field:
        try:
            return qs.order_by(f"-{date_field}", "-id")
        except Exception:
            logger.exception("Failed ordering lab queryset by date field=%s; fallback to -id", date_field)
    try:
        return qs.order_by("-id")
    except Exception:
        logger.exception("Failed ordering lab queryset by -id; returning original queryset")
        return qs


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

    try:
        qs = _lab_doctor_filter(req_model.objects.all(), doctor)
    except Exception:
        logger.exception("Failed to apply doctor filter for lab requests (doctor_id=%s)", getattr(doctor, "id", None))
        messages.error(request, _("Could not load lab requests right now."))
        return redirect(_reverse_any("doctor:dashboard"))

    status_filter = (request.GET.get("status") or "").strip().lower()
    q = (request.GET.get("q") or "").strip()

    status_f = _lab_status_field()
    date_f = _lab_date_field()
    patient_f = _lab_patient_field()

    # Filters
    qs = _apply_status_filter(qs, status_filter=status_filter, status_field=status_f)
    qs = _apply_search_filter(qs, q=q, patient_field=patient_f)
    qs, date_from_str, date_to_str = _apply_date_filter_with_feedback(request, qs, date_field=date_f)

    # Order
    qs = _safe_order_lab_qs(qs, date_field=date_f)

    # Pagination
    per_page = _get_page_size(request, default=10)
    paginator = Paginator(qs, per_page)
    page_obj = paginator.get_page(request.GET.get("page"))

    try:
        stats = _lab_stats_for_doctor(doctor)
    except Exception:
        logger.exception("Failed computing lab stats for doctor_id=%s", getattr(doctor, "id", None))
        stats = {}

    context = {
        "doctor": doctor,

        # Aliases for template compatibility
        "requests": page_obj,
        "orders": page_obj,
        "items": page_obj,
        "page_obj": page_obj,

        # Filters / UI state
        "per_page": per_page,
        "q": q,
        "status": status_filter,
        "date_from": date_from_str,
        "date_to": date_to_str,

        # Feature flags / stats
        "lab_stats": stats,
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

    try:
        qs = _lab_doctor_filter(req_model.objects.all(), doctor)
    except Exception:
        logger.exception("Failed applying doctor filter in lab detail (doctor_id=%s)", getattr(doctor, "id", None))
        raise Http404(_("Lab request not found."))

    obj = get_object_or_404(qs, pk=request_id)

    result_obj = None
    if res_model:
        for rel in ("lab_request", "request", "order", "test_request"):
            if has_field(res_model, rel):
                try:
                    result_obj = res_model.objects.filter(**{rel: obj}).order_by("-id").first()
                    break
                except Exception:
                    logger.exception(
                        "Failed resolving lab result object via relation=%s for request_id=%s",
                        rel,
                        request_id,
                    )
                    continue

    try:
        stats = _lab_stats_for_doctor(doctor)
    except Exception:
        logger.exception("Failed computing lab stats for detail view doctor_id=%s", getattr(doctor, "id", None))
        stats = {}

    context = {
        "doctor": doctor,

        # Aliases for template compatibility
        "request_obj": obj,
        "order_obj": obj,
        "order": obj,
        "lab_order": obj,
        "lab_request": obj,

        "result_obj": result_obj,
        "lab_stats": stats,
        "has_lab": True,
    }

    template_candidates = [
        "doctor/lab/doctor_request_detail.html",
        "lab/doctor_order_detail.html",
        "lab/lab_order_detail.html",
    ]
    return _render_or_fallback(request, template_candidates, context, "Lab Request Detail")