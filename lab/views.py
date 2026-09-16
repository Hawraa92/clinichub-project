# lab/views.py
from __future__ import annotations

import json
import mimetypes
import posixpath
from datetime import timedelta
from functools import lru_cache
from typing import Any, NoReturn, Optional

from django.apps import apps
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import FieldError, PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Count, Q
from django.http import (
    FileResponse,
    Http404,
    HttpRequest,
    HttpResponse,
    JsonResponse,
)
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import NoReverseMatch
from django.utils.http import content_disposition_header
from django.utils import timezone
from django.views.decorators.http import require_GET

from doctor.models import Doctor
from patient.models import Patient

from .forms import LabOrderCreateForm, LabResultForm, LabSettingsForm
from .models import LabOrder, LabResult, LabSettings
from .access import (
    appointment_matches_patient,
    doctor_appointment_queryset,
    doctor_order_queryset,
    doctor_patient_queryset,
    doctor_result_queryset,
    lab_staff_order_queryset,
    lab_staff_result_queryset,
    resolve_lab_order_tenant_snapshot,
)


# ------------------------------------------------------------
# Roles (عدّليها إذا قيم User.role مختلفة عندج)
# ------------------------------------------------------------
DOCTOR_ROLES = {"doctor"}  # ضيفي مثل {"doctor","physician","dermatologist"} إذا أدواركم مختلفة
LAB_ROLES = {"lab", "laboratory", "lab_tech", "lab_staff"}

# حالات الطلب (لازم تطابق قيم الـ model choices)
ORDER_STATUSES = {
    LabOrder.Status.PENDING,
    LabOrder.Status.IN_PROGRESS,
    LabOrder.Status.READY,
    LabOrder.Status.CANCELLED,
}

# ✅ Actions المقبولة من الأزرار (حتى لو template يرسل send/submit)
VERIFY_ACTIONS = {"verify", "send", "submit", "approve", "ready"}
SAVE_ACTIONS = {"save", "draft", "update"}


# ------------------------------------------------------------
# Django model permissions
# ------------------------------------------------------------
VIEW_LAB_ORDER_PERMISSION = "lab.view_laborder"
ADD_LAB_ORDER_PERMISSION = "lab.add_laborder"
CHANGE_LAB_ORDER_PERMISSION = "lab.change_laborder"

VIEW_LAB_RESULT_PERMISSION = "lab.view_labresult"
ADD_LAB_RESULT_PERMISSION = "lab.add_labresult"
CHANGE_LAB_RESULT_PERMISSION = "lab.change_labresult"

VIEW_LAB_SETTINGS_PERMISSION = "lab.view_labsettings"
CHANGE_LAB_SETTINGS_PERMISSION = "lab.change_labsettings"


# ------------------------------------------------------------
# Cached model fields (يشمل fields + many-to-many)
# ------------------------------------------------------------
@lru_cache(maxsize=1)
def _order_fields() -> set[str]:
    names = {f.name for f in LabOrder._meta.fields}
    try:
        names |= {m.name for m in LabOrder._meta.many_to_many}
    except Exception:
        pass
    return names


def _has_order_field(field_name: str) -> bool:
    """فحص سريع إذا حقل موجود بالموديل (حتى ما نكسر إذا migration مو مطبق بعد)."""
    return field_name in _order_fields()


def _safe_save_update_fields(obj, fields: list[str]) -> None:
    """Save مع update_fields بشكل آمن."""
    existing = {f.name for f in obj._meta.fields}
    use = [f for f in fields if f in existing]
    if use:
        obj.save(update_fields=use)
    else:
        obj.save()


def _file_response(file_field, *, inline: bool) -> FileResponse:
    if not file_field or not getattr(file_field, "name", ""):
        raise Http404("File not found.")

    storage_name = file_field.name
    safe_name = posixpath.basename(str(storage_name).replace("\\", "/")) or "attachment"
    content_type = mimetypes.guess_type(safe_name)[0] or "application/octet-stream"

    try:
        handle = file_field.storage.open(storage_name, "rb")
    except (FileNotFoundError, OSError):
        raise Http404("File not found.")

    response = FileResponse(handle, content_type=content_type)
    disposition = content_disposition_header(
        as_attachment=not inline,
        filename=safe_name,
    )
    if disposition:
        response["Content-Disposition"] = disposition
    response["Cache-Control"] = "private, no-store"
    response["Pragma"] = "no-cache"
    response["X-Content-Type-Options"] = "nosniff"
    return response


# ------------------------------------------------------------
# Helpers (صلاحيات + أدوات)
# ------------------------------------------------------------
def _get_role(user) -> str:
    return (getattr(user, "role", "") or "").strip().lower()


def _has_permission(user, permission: str) -> bool:
    """Return whether an authenticated user owns a Django permission."""
    if not user or not user.is_authenticated:
        return False

    return bool(
        user.is_superuser
        or user.has_perm(permission)
    )


def _require_permission(
    request: HttpRequest,
    permission: str,
    message: str,
) -> None:
    """
    Enforce a model permission inside the view.

    Raising ``PermissionDenied`` uses ClinicHub's custom 403 page and keeps
    direct URLs and POST requests protected even if a navigation button is
    hidden or the URL configuration is changed later.
    """
    if not _has_permission(request.user, permission):
        raise PermissionDenied(message)


def _user_has_doctor_profile(user) -> bool:
    if not user or not user.is_authenticated:
        return False
    return Doctor.objects.filter(user=user).exists()


def is_doctor(user) -> bool:
    """
    Doctor check:
    - superuser => True
    - role in DOCTOR_ROLES => True
    - fallback: if Doctor profile exists => True (helps if role values differ)
    """
    if not user or not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    role = _get_role(user)
    if role in DOCTOR_ROLES:
        return True
    return _user_has_doctor_profile(user)


def is_lab(user) -> bool:
    if not user or not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    return _get_role(user) in LAB_ROLES


def _try_redirect(url_name: str, *, fallback_name: str = "home:index", kwargs: dict | None = None):
    """Redirect آمن: إذا صار NoReverseMatch يروح fallback."""
    try:
        if kwargs:
            return redirect(url_name, **kwargs)
        return redirect(url_name)
    except NoReverseMatch:
        return redirect(fallback_name)


def _deny_lab_area(request: HttpRequest) -> HttpResponse | NoReturn:
    """
    إذا غير المختبر حاول يدخل صفحات المختبر:
    - الطبيب: نرجعه لواجهة طلباته بالمختبر
    - غير ذلك: 403
    """
    if is_doctor(request.user) and not is_lab(request.user):
        messages.warning(request, "هذه الصفحة خاصة بالمختبر. تم تحويلك لواجهة الطبيب.")
        return _try_redirect("lab:doctor_orders_inbox", fallback_name="doctor:dashboard")
    raise PermissionDenied(
        "Your account is not allowed to access the laboratory staff area."
    )


def _deny_doctor_area(request: HttpRequest) -> HttpResponse | NoReturn:
    """
    إذا غير الطبيب حاول يدخل صفحات الطبيب الخاصة بطلبات المختبر:
    - المختبر: نرجعه لداشبورد المختبر
    - غير ذلك: 403
    """
    if is_lab(request.user) and not is_doctor(request.user):
        messages.warning(request, "هذه الصفحة خاصة بالطبيب. تم تحويلك لواجهة المختبر.")
        return _try_redirect("lab:dashboard", fallback_name="home:index")
    raise PermissionDenied(
        "Your account is not allowed to access the doctor's laboratory area."
    )


def _get_lab_settings() -> LabSettings:
    """جلب إعدادات المختبر بشكل آمن سواء كنتِ تستخدمين django-solo أو لا."""
    if hasattr(LabSettings, "get_solo"):
        return LabSettings.get_solo()

    obj = LabSettings.objects.first()
    if obj:
        return obj
    return LabSettings.objects.create()


def _laborder_text_search_q_basic(q: str) -> Q:
    """
    بحث آمن 100% (بدون M2M) حتى ما يصير FieldError.
    """
    q = (q or "").strip()
    if not q:
        return Q()

    fields = _order_fields()
    cond = Q(patient__full_name__icontains=q)

    if "requested_tests_text" in fields:
        cond |= Q(requested_tests_text__icontains=q)
    if "notes" in fields:
        cond |= Q(notes__icontains=q)

    return cond


def _laborder_text_search_q(q: str) -> Q:
    """
    يبني Q للبحث.
    - الأساس يعتمد على patient/full_name + requested_tests_text + notes
    - إذا عندج requested_tests (M2M) نحاول نضيفه بشكل best-effort
      بس بما إن أسماء حقول الـ M2M تختلف (name/title/...) نخليها optional ونعالج FieldError لاحقًا.
    """
    q = (q or "").strip()
    if not q:
        return Q()

    fields = _order_fields()
    cond = _laborder_text_search_q_basic(q)

    # best-effort only; may raise FieldError depending on relation fields
    if "requested_tests" in fields:
        # إذا كانت relation، هذا قد يحتاج requested_tests__name__icontains
        # لكن ما نعرف اسم الحقل؛ نخلي محاولة عامة ونلتقط FieldError عند apply.
        cond |= Q(requested_tests__icontains=q)

    return cond


def _get_doctor_profile(user) -> Optional[Doctor]:
    """يرجع Doctor profile أو None بدل 404 حتى نعطي رسالة واضحة."""
    try:
        return Doctor.objects.select_related("user").get(user=user)
    except Doctor.DoesNotExist:
        return None


def _build_result_form(*, request: HttpRequest, instance: LabResult, settings_obj: LabSettings) -> Any:
    """يبني LabResultForm بشكل آمن حتى لو الفورم ما يدعم settings_obj."""
    if request.method == "POST":
        try:
            return LabResultForm(request.POST, request.FILES, instance=instance, settings_obj=settings_obj)
        except TypeError:
            return LabResultForm(request.POST, request.FILES, instance=instance)
    else:
        try:
            return LabResultForm(instance=instance, settings_obj=settings_obj)
        except TypeError:
            return LabResultForm(instance=instance)


def _infer_patient_from_order(order: LabOrder) -> Optional[Patient]:
    """
    يستنتج المريض تلقائياً من الـ appointment إذا موجودة داخل LabOrder.
    يدعم:
    - order.appointment (FK object)
    - order.appointment_id (FK id)
    """
    appt_obj = getattr(order, "appointment", None)
    if appt_obj is not None:
        pid = getattr(appt_obj, "patient_id", None)
        if pid:
            return getattr(appt_obj, "patient", None)

    appt_id = getattr(order, "appointment_id", None)
    if appt_id:
        try:
            Appointment = apps.get_model("appointments", "Appointment")
            appt = (
                Appointment.objects
                .select_related("patient", "doctor")
                .filter(pk=appt_id)
                .first()
            )
            if appt and getattr(appt, "patient_id", None):
                return appt.patient
        except Exception:
            return None

    return None


def _appointment_belongs_to_doctor(order: LabOrder, doctor: Doctor) -> bool:
    """
    تحقق اختياري قوي: إذا الطلب مرتبط بموعد، لازم الموعد يكون لنفس الطبيب.
    إذا ماكو appointment أصلاً → True.
    """
    appt_obj = getattr(order, "appointment", None)
    if appt_obj is not None:
        appt_doctor_id = getattr(appt_obj, "doctor_id", None)
        return (appt_doctor_id is None) or (appt_doctor_id == doctor.id)

    appt_id = getattr(order, "appointment_id", None)
    if appt_id:
        try:
            Appointment = apps.get_model("appointments", "Appointment")
            appt = Appointment.objects.only("doctor_id").filter(pk=appt_id).first()
            if not appt:
                return True
            return (getattr(appt, "doctor_id", None) is None) or (appt.doctor_id == doctor.id)
        except Exception:
            return True

    return True


def _normalize_action(raw: str) -> str:
    """
    Normalize incoming action from template buttons/inputs.
    Accepts multiple names for verify/send.
    """
    a = (raw or "").strip().lower()
    if not a:
        return "save"
    if a in VERIFY_ACTIONS:
        return "verify"
    if a in SAVE_ACTIONS:
        return "save"
    return "save"


# ------------------------------------------------------------
# Doctor notifications (READY unseen count) + Doctor KPIs
# ------------------------------------------------------------
def _doctor_ready_count(user, doctor: Doctor) -> int:
    """
    عدد النتائج الجاهزة للطبيب (READY) وغير المقروءة.
    إذا يوجد doctor_seen_at → نعد فقط doctor_seen_at IS NULL
    إذا غير موجود → نعد كل READY.
    """
    qs = doctor_order_queryset(
        user,
        doctor,
        LabOrder.objects.filter(status=LabOrder.Status.READY),
    )
    if _has_order_field("doctor_seen_at"):
        qs = qs.filter(doctor_seen_at__isnull=True)
    return qs.count()


def _doctor_kpis(user, doctor: Doctor) -> dict[str, int]:
    """
    ✅ أرقام ثابتة للطبيب (لا تعتمد على التبويب الحالي بالـ inbox)
    """
    today = timezone.localdate()
    base = doctor_order_queryset(user, doctor)

    completed_results = base.filter(status=LabOrder.Status.READY).count()

    # Ready Today (دقيق إذا ready_at موجود)
    if _has_order_field("ready_at"):
        ready_today = base.filter(status=LabOrder.Status.READY, ready_at__date=today).count()
    else:
        ready_today = base.filter(status=LabOrder.Status.READY, created_at__date=today).count()

    return {
        "pending": base.filter(status=LabOrder.Status.PENDING).count(),
        "in_progress": base.filter(status=LabOrder.Status.IN_PROGRESS).count(),
        "cancelled": base.filter(status=LabOrder.Status.CANCELLED).count(),
        "completed_results": completed_results,
        "ready_today": ready_today,
        "today_requests": base.filter(created_at__date=today).count(),
    }


def _mark_seen_by_doctor_if_ready(order: LabOrder) -> None:
    """أول ما الطبيب يفتح تفاصيل طلب READY: نخليه مقروء."""
    if order.status != LabOrder.Status.READY:
        return
    if not _has_order_field("doctor_seen_at"):
        return
    if getattr(order, "doctor_seen_at", None) is None:
        order.doctor_seen_at = timezone.now()
        _safe_save_update_fields(order, ["doctor_seen_at"])


# ------------------------------------------------------------
# Lab "Seen" (when lab opens request)
# ------------------------------------------------------------
def _mark_order_seen_if_pending(order: LabOrder, user) -> None:
    """
    أول ما المختبر يفتح الطلب (GET) وإذا كان PENDING → يتحول IN_PROGRESS.
    """
    if order.status != LabOrder.Status.PENDING:
        return

    now = timezone.now()
    fields = _order_fields()
    update_fields: list[str] = []

    order.status = LabOrder.Status.IN_PROGRESS
    update_fields.append("status")

    # Optional tracking fields (إذا موجودة)
    if "seen_at" in fields and not getattr(order, "seen_at", None):
        order.seen_at = now
        update_fields.append("seen_at")

    if "seen_by" in fields and not getattr(order, "seen_by_id", None):
        order.seen_by = user
        update_fields.append("seen_by")

    if "last_seen_at" in fields:
        order.last_seen_at = now
        update_fields.append("last_seen_at")

    if "last_seen_by" in fields:
        order.last_seen_by = user
        update_fields.append("last_seen_by")

    _safe_save_update_fields(order, update_fields)


# ------------------------------------------------------------
# Doctor API (DOCTOR ONLY) - for polling badge/notifications
# ------------------------------------------------------------
@require_GET
@login_required
def doctor_ready_count_api(request: HttpRequest) -> JsonResponse:
    """Returns JSON: {"count": <READY unseen orders for this doctor>}"""
    if not is_doctor(request.user):
        return JsonResponse({"count": 0}, status=403)

    _require_permission(
        request,
        VIEW_LAB_ORDER_PERMISSION,
        "You do not have permission to view laboratory orders.",
    )

    doctor = _get_doctor_profile(request.user)
    if not doctor:
        return JsonResponse({"count": 0})

    return JsonResponse({"count": _doctor_ready_count(request.user, doctor)})


@require_GET
@login_required
def lab_staff_doctor_attachment_file(
    request: HttpRequest,
    order_id: int,
    *,
    inline: bool,
) -> FileResponse:
    if not is_lab(request.user):
        return _deny_lab_area(request)

    _require_permission(
        request,
        VIEW_LAB_ORDER_PERMISSION,
        "You do not have permission to view laboratory orders.",
    )

    order = get_object_or_404(
        lab_staff_order_queryset(
            request.user,
            LabOrder.objects.only("pk", "doctor_attachment", "hospital", "branch"),
        ),
        pk=order_id,
    )
    return _file_response(order.doctor_attachment, inline=inline)


@require_GET
@login_required
def lab_staff_result_attachment_file(
    request: HttpRequest,
    order_id: int,
    *,
    inline: bool,
) -> FileResponse:
    if not is_lab(request.user):
        return _deny_lab_area(request)

    _require_permission(
        request,
        VIEW_LAB_RESULT_PERMISSION,
        "You do not have permission to view laboratory results.",
    )

    result = get_object_or_404(
        lab_staff_result_queryset(
            request.user,
            LabResult.objects.select_related("order").only(
                "pk",
                "order",
                "attachment",
                "order__hospital",
                "order__branch",
            ),
        ),
        order_id=order_id,
    )
    return _file_response(result.attachment, inline=inline)


@require_GET
@login_required
def doctor_order_doctor_attachment_file(
    request: HttpRequest,
    order_id: int,
    *,
    inline: bool,
) -> FileResponse:
    if not is_doctor(request.user):
        return _deny_doctor_area(request)

    _require_permission(
        request,
        VIEW_LAB_ORDER_PERMISSION,
        "You do not have permission to view laboratory orders.",
    )

    doctor = _get_doctor_profile(request.user)
    if not doctor:
        raise Http404("Order not found.")

    order = get_object_or_404(
        doctor_order_queryset(
            request.user,
            doctor,
            LabOrder.objects.only(
                "pk",
                "doctor",
                "doctor_attachment",
                "hospital",
                "branch",
            ),
        ),
        pk=order_id,
    )
    return _file_response(order.doctor_attachment, inline=inline)


@require_GET
@login_required
def doctor_result_attachment_file(
    request: HttpRequest,
    order_id: int,
    *,
    inline: bool,
) -> FileResponse:
    if not is_doctor(request.user):
        return _deny_doctor_area(request)

    _require_permission(
        request,
        VIEW_LAB_RESULT_PERMISSION,
        "You do not have permission to view laboratory results.",
    )

    doctor = _get_doctor_profile(request.user)
    if not doctor:
        raise Http404("Result not found.")

    result = get_object_or_404(
        doctor_result_queryset(
            request.user,
            doctor,
            LabResult.objects.select_related("order").only(
                "pk",
                "order",
                "attachment",
                "order__doctor",
                "order__hospital",
                "order__branch",
            ),
        ),
        order_id=order_id,
    )
    return _file_response(result.attachment, inline=inline)


# ------------------------------------------------------------
# Lab Dashboard (LAB ONLY)
# ------------------------------------------------------------
@login_required
def lab_dashboard(request: HttpRequest) -> HttpResponse:
    if not is_lab(request.user):
        return _deny_lab_area(request)

    _require_permission(
        request,
        VIEW_LAB_ORDER_PERMISSION,
        "You do not have permission to view the laboratory dashboard.",
    )

    today = timezone.localdate()
    settings_obj = _get_lab_settings()

    status_filter = (request.GET.get("status", "") or "").strip().upper()
    q = (request.GET.get("q", "") or "").strip()

    base_qs = lab_staff_order_queryset(
        request.user,
        LabOrder.objects.select_related("patient", "doctor__user"),
    )
    if status_filter in ORDER_STATUSES:
        base_qs = base_qs.filter(status=status_filter)

    if q:
        # تطبيق البحث مع fallback إذا صار FieldError بسبب requested_tests
        try:
            base_qs = base_qs.filter(_laborder_text_search_q(q))
        except FieldError:
            base_qs = base_qs.filter(_laborder_text_search_q_basic(q))

    qs_all = lab_staff_order_queryset(request.user)

    pending = qs_all.filter(status=LabOrder.Status.PENDING).count()
    in_progress = qs_all.filter(status=LabOrder.Status.IN_PROGRESS).count()

    today_requests = qs_all.filter(created_at__date=today).count()
    completed_total = qs_all.filter(status=LabOrder.Status.READY).count()

    if _has_order_field("ready_at"):
        completed_today = qs_all.filter(status=LabOrder.Status.READY, ready_at__date=today).count()
    else:
        completed_today = qs_all.filter(status=LabOrder.Status.READY, created_at__date=today).count()

    fields = _order_fields()
    if "priority" in fields:
        urgent_pending = qs_all.filter(
            priority__iexact="urgent",
            status__in=[LabOrder.Status.PENDING, LabOrder.Status.IN_PROGRESS],
        ).count()
    elif "urgency" in fields:
        urgent_pending = qs_all.filter(
            urgency__iexact="urgent",
            status__in=[LabOrder.Status.PENDING, LabOrder.Status.IN_PROGRESS],
        ).count()
    else:
        urgent_pending = 0

    latest_orders = (
        lab_staff_order_queryset(
            request.user,
            LabOrder.objects.select_related("patient", "doctor__user"),
        )
        .order_by("-created_at")[:12]
    )

    start_week = today - timedelta(days=today.weekday())
    end_week = start_week + timedelta(days=6)
    labels = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    days = [start_week + timedelta(days=i) for i in range(7)]

    week_counts = dict(
        qs_all.filter(created_at__date__gte=start_week, created_at__date__lte=end_week)
        .values("created_at__date")
        .annotate(c=Count("id"))
        .values_list("created_at__date", "c")
    )
    data = [week_counts.get(d, 0) for d in days]
    chart_data_json = json.dumps({"labels": labels, "data": data})

    context = {
        "today": today,
        "settings_obj": settings_obj,
        "stats": {
            "pending": pending,
            "in_progress": in_progress,
            "urgent_pending": urgent_pending,
            "completed_total": completed_total,
            "completed_results": completed_total,
            "completed_today": completed_today,
            "today_requests": today_requests,
        },
        "latest_orders": latest_orders,
        "chart_data_json": chart_data_json,
        "q": q,
        "status_filter": status_filter,
        "orders_filtered": base_qs.order_by("-created_at")[:50],
        "can_view_lab_settings": _has_permission(
            request.user,
            VIEW_LAB_SETTINGS_PERMISSION,
        ),
        "can_change_lab_settings": _has_permission(
            request.user,
            CHANGE_LAB_SETTINGS_PERMISSION,
        ),
    }
    return render(request, "lab/lab_dashboard.html", context)


# ------------------------------------------------------------
# Lab Settings (LAB ONLY)
# ------------------------------------------------------------
@login_required
def lab_settings(request: HttpRequest) -> HttpResponse:
    if not is_lab(request.user):
        return _deny_lab_area(request)

    if request.method == "POST":
        _require_permission(
            request,
            CHANGE_LAB_SETTINGS_PERMISSION,
            "You do not have permission to change laboratory settings.",
        )
    else:
        _require_permission(
            request,
            VIEW_LAB_SETTINGS_PERMISSION,
            "You do not have permission to view laboratory settings.",
        )

    obj = _get_lab_settings()

    if request.method == "POST":
        form = LabSettingsForm(request.POST, request.FILES, instance=obj)
        if form.is_valid():
            form.save()
            messages.success(request, "✅ Lab settings saved successfully.")
            return redirect("lab:lab_settings")
        messages.error(request, "❌ Please correct the errors below.")
    else:
        form = LabSettingsForm(instance=obj)

    return render(
        request,
        "lab/lab_settings.html",
        {
            "form": form,
            "settings_obj": obj,
            "can_change_lab_settings": _has_permission(
                request.user,
                CHANGE_LAB_SETTINGS_PERMISSION,
            ),
        },
    )


# ------------------------------------------------------------
# Doctor views (DOCTOR ONLY)
# ------------------------------------------------------------
@login_required
def doctor_orders_inbox(request: HttpRequest) -> HttpResponse:
    if not is_doctor(request.user):
        return _deny_doctor_area(request)

    _require_permission(
        request,
        VIEW_LAB_ORDER_PERMISSION,
        "You do not have permission to view laboratory orders.",
    )

    doctor = _get_doctor_profile(request.user)
    if not doctor:
        messages.error(request, "لا يوجد ملف Doctor مرتبط بهذا المستخدم.")
        return _try_redirect("doctor:dashboard", fallback_name="home:index")

    ready_count = _doctor_ready_count(request.user, doctor)
    doctor_stats = _doctor_kpis(request.user, doctor)

    status = (request.GET.get("status", LabOrder.Status.PENDING) or "").strip().upper()
    if status not in ORDER_STATUSES:
        status = LabOrder.Status.PENDING

    q = (request.GET.get("q", "") or "").strip()

    qs = (
        doctor_order_queryset(
            request.user,
            doctor,
            LabOrder.objects.select_related("patient", "doctor__user"),
        )
        .filter(status=status)
    )

    if q:
        try:
            qs = qs.filter(_laborder_text_search_q(q))
        except FieldError:
            qs = qs.filter(_laborder_text_search_q_basic(q))

    qs = qs.order_by("-created_at")[:200]

    return render(
        request,
        "lab/doctor_orders_inbox.html",
        {
            "orders": qs,
            "status": status,
            "q": q,
            "readonly": True,
            "ready_count": ready_count,
            "stats": doctor_stats,
            "can_add_lab_order": _has_permission(
                request.user,
                ADD_LAB_ORDER_PERMISSION,
            ),
            "can_view_lab_result": _has_permission(
                request.user,
                VIEW_LAB_RESULT_PERMISSION,
            ),
        },
    )


@login_required
def doctor_create_lab_order(request: HttpRequest, patient_id: int | None = None) -> HttpResponse:
    if not is_doctor(request.user):
        return _deny_doctor_area(request)

    _require_permission(
        request,
        ADD_LAB_ORDER_PERMISSION,
        "You do not have permission to create laboratory orders.",
    )

    doctor = _get_doctor_profile(request.user)
    if not doctor:
        messages.error(request, "لا يوجد ملف Doctor مرتبط بهذا المستخدم.")
        return _try_redirect("doctor:dashboard", fallback_name="home:index")

    ready_count = _doctor_ready_count(request.user, doctor)
    appointment_qs = doctor_appointment_queryset(request.user, doctor)
    patient_qs = doctor_patient_queryset(request.user, doctor)

    patient: Optional[Patient] = None
    if patient_id is not None:
        patient = get_object_or_404(patient_qs, pk=patient_id)

    if request.method == "POST":
        form = LabOrderCreateForm(
            request.POST,
            request.FILES,
            appointment_queryset=appointment_qs,
        )
        if form.is_valid():
            order: LabOrder = form.save(commit=False)

            # 1) patient من الرابط أولاً
            if patient is not None:
                order.patient = patient

            # 2) إذا ماكو patient، استنتجه من appointment
            if not getattr(order, "patient_id", None):
                inferred = _infer_patient_from_order(order)
                if inferred is not None:
                    order.patient = inferred

            # 3) لازم يكون صار عندنا patient بالنهاية
            if not getattr(order, "patient_id", None):
                messages.error(request, "رجاءً اختاري المريض قبل إنشاء طلب المختبر.")
                return render(
                    request,
                    "lab/doctor_create_order.html",
                    {"form": form, "patient": patient, "ready_count": ready_count},
                )

            # 4) appointment (إن وجد) لازم يخص نفس الطبيب
            if not _appointment_belongs_to_doctor(order, doctor):
                messages.error(request, "الـ Appointment المختار لا يخص هذا الطبيب.")
                return render(
                    request,
                    "lab/doctor_create_order.html",
                    {"form": form, "patient": patient, "ready_count": ready_count},
                )

            if not patient_qs.filter(pk=order.patient_id).exists():
                messages.error(request, "Selected patient is not available to this doctor.")
                return render(
                    request,
                    "lab/doctor_create_order.html",
                    {"form": form, "patient": patient, "ready_count": ready_count},
                    status=404,
                )

            if (
                getattr(order, "appointment_id", None)
                and not appointment_qs.filter(pk=order.appointment_id).exists()
            ):
                messages.error(request, "Selected appointment is not available.")
                return render(
                    request,
                    "lab/doctor_create_order.html",
                    {"form": form, "patient": patient, "ready_count": ready_count},
                    status=404,
                )

            if not appointment_matches_patient(
                getattr(order, "appointment", None),
                order.patient,
            ):
                messages.error(request, "Selected appointment does not belong to the selected patient.")
                return render(
                    request,
                    "lab/doctor_create_order.html",
                    {"form": form, "patient": patient, "ready_count": ready_count},
                    status=400,
                )

            order.doctor = doctor
            order.status = LabOrder.Status.PENDING

            try:
                hospital_id, branch_id = resolve_lab_order_tenant_snapshot(
                    order,
                    explicit_hospital_id=request.POST.get("hospital"),
                    explicit_branch_id=request.POST.get("branch"),
                )
            except ValidationError as exc:
                messages.error(request, "Selected laboratory tenant context is not valid.")
                form.add_error(None, " ".join(exc.messages))
                return render(
                    request,
                    "lab/doctor_create_order.html",
                    {"form": form, "patient": patient, "ready_count": ready_count},
                    status=400,
                )

            order.hospital_id = hospital_id
            order.branch_id = branch_id

            # تنظيف النصوص
            if _has_order_field("requested_tests_text"):
                order.requested_tests_text = (getattr(order, "requested_tests_text", "") or "").strip()
            if _has_order_field("notes"):
                order.notes = (getattr(order, "notes", "") or "").strip()

            order.save()
            messages.success(request, "✅ تم إرسال طلب المختبر.")
            return redirect("lab:doctor_order_detail", order_id=order.id)

        messages.error(request, "❌ تأكدي من الحقول.")
    else:
        form = LabOrderCreateForm(appointment_queryset=appointment_qs)

    return render(
        request,
        "lab/doctor_create_order.html",
        {"form": form, "patient": patient, "ready_count": ready_count},
    )


@login_required
def doctor_order_detail(request: HttpRequest, order_id: int) -> HttpResponse:
    if not is_doctor(request.user):
        return _deny_doctor_area(request)

    _require_permission(
        request,
        VIEW_LAB_ORDER_PERMISSION,
        "You do not have permission to view laboratory orders.",
    )

    doctor = _get_doctor_profile(request.user)
    if not doctor:
        messages.error(request, "لا يوجد ملف Doctor مرتبط بهذا المستخدم.")
        return _try_redirect("doctor:dashboard", fallback_name="home:index")

    order = get_object_or_404(
        doctor_order_queryset(
            request.user,
            doctor,
            LabOrder.objects.select_related("patient", "doctor__user"),
        ),
        pk=order_id,
    )

    can_view_result = _has_permission(
        request.user,
        VIEW_LAB_RESULT_PERMISSION,
    )
    result = (
        doctor_result_queryset(
            request.user,
            doctor,
            LabResult.objects.filter(order=order),
        ).first()
        if can_view_result
        else None
    )

    ready_count = _doctor_ready_count(request.user, doctor)

    return render(
        request,
        "lab/doctor_order_detail.html",
        {
            "order": order,
            "result": result,
            "ready_count": ready_count,
            "can_view_lab_result": can_view_result,
        },
    )


# ------------------------------------------------------------
# Lab views (LAB ONLY)
# ------------------------------------------------------------
@login_required
def lab_inbox(request: HttpRequest) -> HttpResponse:
    if not is_lab(request.user):
        return _deny_lab_area(request)

    _require_permission(
        request,
        VIEW_LAB_ORDER_PERMISSION,
        "You do not have permission to view laboratory orders.",
    )

    settings_obj = _get_lab_settings()

    status = (request.GET.get("status", LabOrder.Status.PENDING) or "").strip().upper()
    if status not in ORDER_STATUSES:
        status = LabOrder.Status.PENDING

    q = (request.GET.get("q", "") or "").strip()

    qs = (
        lab_staff_order_queryset(
            request.user,
            LabOrder.objects.select_related("patient", "doctor__user"),
        )
        .filter(status=status)
    )

    if q:
        try:
            qs = qs.filter(_laborder_text_search_q(q))
        except FieldError:
            qs = qs.filter(_laborder_text_search_q_basic(q))

    qs = qs.order_by("-created_at")[:200]

    return render(
        request,
        "lab/lab_inbox.html",
        {
            "orders": qs,
            "status": status,
            "q": q,
            "settings_obj": settings_obj,
            "can_view_lab_settings": _has_permission(
                request.user,
                VIEW_LAB_SETTINGS_PERMISSION,
            ),
            "can_change_lab_order": _has_permission(
                request.user,
                CHANGE_LAB_ORDER_PERMISSION,
            ),
            "can_view_lab_result": _has_permission(
                request.user,
                VIEW_LAB_RESULT_PERMISSION,
            ),
        },
    )


@login_required
def lab_order_detail(request: HttpRequest, order_id: int) -> HttpResponse:
    """
    Laboratory order detail with method-specific permissions.

    Security rules:
    - The user must be a laboratory staff member.
    - Viewing the order requires ``lab.view_laborder``.
    - Creating the first result requires ``lab.add_labresult``.
    - Editing or verifying an existing result requires
      ``lab.change_labresult``.
    - Any POST that can move the order workflow requires
      ``lab.change_laborder``.
    - Cancelled orders cannot be updated or verified.
    """
    if not is_lab(request.user):
        if is_doctor(request.user):
            messages.info(request, "هذه صفحة المختبر. تم تحويلك لعرض الطلب كطبيب.")
            return _try_redirect(
                "lab:doctor_order_detail",
                fallback_name="doctor:dashboard",
                kwargs={"order_id": order_id},
            )
        return _deny_lab_area(request)

    _require_permission(
        request,
        VIEW_LAB_ORDER_PERMISSION,
        "You do not have permission to view laboratory orders.",
    )

    order = get_object_or_404(
        lab_staff_order_queryset(
            request.user,
            LabOrder.objects.select_related("patient", "doctor__user"),
        ),
        pk=order_id,
    )

    settings_obj = _get_lab_settings()
    require_verify = bool(getattr(settings_obj, "require_verify_before_ready", True))

    can_change_order = _has_permission(
        request.user,
        CHANGE_LAB_ORDER_PERMISSION,
    )
    can_view_result = _has_permission(
        request.user,
        VIEW_LAB_RESULT_PERMISSION,
    )
    can_add_result = _has_permission(
        request.user,
        ADD_LAB_RESULT_PERMISSION,
    )
    can_change_result = _has_permission(
        request.user,
        CHANGE_LAB_RESULT_PERMISSION,
    )

    existing_result = lab_staff_result_queryset(
        request.user,
        LabResult.objects.filter(order=order),
    ).first()

    if request.method == "POST":
        action = _normalize_action(request.POST.get("action", "save"))

        _require_permission(
            request,
            CHANGE_LAB_ORDER_PERMISSION,
            "You do not have permission to update the laboratory workflow.",
        )

        if existing_result is None:
            _require_permission(
                request,
                ADD_LAB_RESULT_PERMISSION,
                "You do not have permission to create laboratory results.",
            )
            result_instance = LabResult(order=order)
        else:
            _require_permission(
                request,
                CHANGE_LAB_RESULT_PERMISSION,
                "You do not have permission to change laboratory results.",
            )
            result_instance = existing_result

        if action == "verify" or not require_verify:
            _require_permission(
                request,
                CHANGE_LAB_RESULT_PERMISSION,
                "You do not have permission to verify laboratory results.",
            )

        if order.status == LabOrder.Status.CANCELLED:
            messages.error(request, "❌ This order is cancelled and cannot be updated or sent.")
            return redirect("lab:lab_order_detail", order_id=order.id)

        form = _build_result_form(
            request=request,
            instance=result_instance,
            settings_obj=settings_obj,
        )

        if form.is_valid():
            with transaction.atomic():
                result = form.save()

                if action == "verify":
                    # The model marks the result VERIFIED, moves the order to
                    # READY and resets doctor_seen_at.
                    result.verify(request.user)
                    messages.success(request, "✅ تم اعتماد النتيجة وإرسالها للطبيب.")
                else:
                    if order.status == LabOrder.Status.PENDING:
                        order.status = LabOrder.Status.IN_PROGRESS
                        _safe_save_update_fields(order, ["status"])

                    if not require_verify:
                        result.verify(request.user)
                        messages.success(request, "✅ تم حفظ النتيجة وإرسالها للطبيب.")
                    else:
                        messages.success(request, "💾 تم حفظ النتيجة كمسودة.")

            return redirect("lab:lab_order_detail", order_id=order.id)

        messages.error(request, "❌ تأكدي من المدخلات.")
    else:
        can_edit_result = (
            can_change_result
            if existing_result is not None
            else can_add_result
        )

        if can_edit_result and can_change_order:
            result_instance = (
                existing_result
                if existing_result is not None
                else LabResult(order=order)
            )
            form = _build_result_form(
                request=request,
                instance=result_instance,
                settings_obj=settings_obj,
            )
        else:
            form = None

    visible_result = (
        existing_result
        if existing_result is not None
        and (
            can_view_result
            or can_change_result
        )
        else None
    )

    return render(
        request,
        "lab/lab_order_detail.html",
        {
            "order": order,
            "form": form,
            "result": visible_result,
            "settings_obj": settings_obj,
            "require_verify": require_verify,
            "can_change_lab_order": can_change_order,
            "can_view_lab_result": can_view_result,
            "can_add_lab_result": can_add_result,
            "can_change_lab_result": can_change_result,
            "can_edit_lab_result": bool(form),
        },
    )
