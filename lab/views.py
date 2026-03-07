from __future__ import annotations

import json
from datetime import timedelta
from functools import lru_cache
from typing import Any, Optional

from django.apps import apps
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import FieldError
from django.db import transaction
from django.db.models import Count, Q
from django.http import (
    HttpRequest,
    HttpResponse,
    HttpResponseForbidden,
    JsonResponse,
)
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import NoReverseMatch
from django.utils import timezone
from django.views.decorators.http import require_GET

from doctor.models import Doctor
from patient.models import Patient

from .forms import LabOrderCreateForm, LabResultForm, LabSettingsForm
from .models import LabOrder, LabResult, LabSettings


# ------------------------------------------------------------
# Roles (عدّليها إذا قيم User.role مختلفة عندج)
# ------------------------------------------------------------
DOCTOR_ROLES = {"doctor"}
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
# Optional policy toggles
# ------------------------------------------------------------
def _enforce_doctor_patient_scope() -> bool:
    """
    إذا True: الطبيب ما يگدر ينشئ LabOrder لمريض خارج نطاقه.
    الافتراضي False حتى ما نكسر أي سلوك قديم، وتكدرين تفعليه من settings:
      LAB_DOCTOR_ENFORCE_PATIENT_SCOPE=True
    """
    return bool(getattr(settings, "LAB_DOCTOR_ENFORCE_PATIENT_SCOPE", False))


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


# ------------------------------------------------------------
# Helpers (صلاحيات + أدوات)
# ------------------------------------------------------------
def _get_role(user) -> str:
    return (getattr(user, "role", "") or "").strip().lower()


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


def _deny_lab_area(request: HttpRequest) -> HttpResponse:
    """
    إذا غير المختبر حاول يدخل صفحات المختبر:
    - الطبيب: نرجعه لواجهة طلباته بالمختبر
    - غير ذلك: 403
    """
    if is_doctor(request.user) and not is_lab(request.user):
        messages.warning(request, "هذه الصفحة خاصة بالمختبر. تم تحويلك لواجهة الطبيب.")
        return _try_redirect("lab:doctor_orders_inbox", fallback_name="doctor:dashboard")
    return HttpResponseForbidden("Forbidden")


def _deny_doctor_area(request: HttpRequest) -> HttpResponse:
    """
    إذا غير الطبيب حاول يدخل صفحات الطبيب الخاصة بطلبات المختبر:
    - المختبر: نرجعه لداشبورد المختبر
    - غير ذلك: 403
    """
    if is_lab(request.user) and not is_doctor(request.user):
        messages.warning(request, "هذه الصفحة خاصة بالطبيب. تم تحويلك لواجهة المختبر.")
        return _try_redirect("lab:dashboard", fallback_name="home:index")
    return HttpResponseForbidden("Forbidden")


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


def _m2m_requested_tests_search_q(q: str) -> Q:
    """
    محاولة ذكية للبحث ضمن requested_tests (ManyToMany) بدون كسر:
    نبحث على حقول شائعة في جدول الفحوصات: name/title/code/label...
    إذا ما نكدر نحدد حقل مناسب، نرجع Q() فقط.
    """
    q = (q or "").strip()
    if not q:
        return Q()

    try:
        f = LabOrder._meta.get_field("requested_tests")  # type: ignore[attr-defined]
        related_model = getattr(f, "related_model", None)
        if not related_model:
            return Q()

        candidate_fields = ("name", "title", "label", "code", "test_name", "test", "short_name")
        related_field_names = {x.name for x in related_model._meta.fields}

        chosen = next((c for c in candidate_fields if c in related_field_names), None)
        if not chosen:
            return Q()

        return Q(**{f"requested_tests__{chosen}__icontains": q})
    except Exception:
        return Q()


def _laborder_text_search_q(q: str) -> Q:
    """
    يبني Q للبحث.
    - الأساس يعتمد على patient/full_name + requested_tests_text + notes
    - وإذا requested_tests (M2M) موجودة: نضيف بحث ذكي على name/title/code...
    """
    q = (q or "").strip()
    if not q:
        return Q()

    cond = _laborder_text_search_q_basic(q)

    if "requested_tests" in _order_fields():
        cond |= _m2m_requested_tests_search_q(q)

    return cond


def _get_doctor_profile(user) -> Optional[Doctor]:
    """يرجع Doctor profile أو None بدل 404 حتى نعطي رسالة واضحة."""
    try:
        return Doctor.objects.select_related("user").get(user=user)
    except Doctor.DoesNotExist:
        return None


def _doctor_can_access_patient(doctor: Doctor, patient: Patient) -> bool:
    """
    تحقق نطاق المريض للطبيب (اختياري حسب setting).
    يدعم:
    - Patient.doctor FK إذا موجود
    - Appointment linkage إذا موجود
    """
    if not doctor or not patient:
        return False

    try:
        if getattr(patient, "doctor_id", None) == doctor.id:
            return True
    except Exception:
        pass

    try:
        Appointment = apps.get_model("appointments", "Appointment")
        if Appointment and Appointment.objects.filter(doctor=doctor, patient=patient).exists():
            return True
    except Exception:
        pass

    return False


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


def _doctor_appointments_qs(doctor: Doctor, patient: Patient | None = None):
    """
    مواعيد الطبيب فقط، ومربوطة بمريض، وغير ملغية قدر الإمكان.
    تستخدم لتقييد حقل appointment في نموذج إنشاء طلب المختبر.
    """
    try:
        Appointment = apps.get_model("appointments", "Appointment")
    except Exception:
        return None

    qs = (
        Appointment.objects
        .select_related("patient", "doctor")
        .filter(doctor=doctor, patient__isnull=False)
    )

    if patient is not None:
        qs = qs.filter(patient=patient)

    try:
        qs = qs.exclude(status__iexact="cancelled")
    except Exception:
        pass

    try:
        qs = qs.order_by("-scheduled_time")
    except Exception:
        qs = qs.order_by("-pk")

    return qs


def _configure_doctor_order_form(form: LabOrderCreateForm, doctor: Doctor, patient: Patient | None = None) -> None:
    """
    يقيّد appointment للطبيب الحالي فقط، ويجعله اختياريًا إذا patient معروف من الرابط.
    """
    if "appointment" not in form.fields:
        return

    appt_qs = _doctor_appointments_qs(doctor, patient=patient)
    if appt_qs is not None:
        form.fields["appointment"].queryset = appt_qs

    form.fields["appointment"].required = patient is None

    if patient is not None:
        form.fields["appointment"].help_text = "يمكنك ترك الموعد فارغًا لأن المريض محدد مسبقًا."
    else:
        form.fields["appointment"].help_text = "اختاري موعدًا يخص هذا الطبيب ومربوطًا بمريض."


# ------------------------------------------------------------
# Doctor notifications (READY unseen count) + Doctor KPIs
# ------------------------------------------------------------
def _doctor_ready_count(doctor: Doctor) -> int:
    """
    عدد النتائج الجاهزة للطبيب (READY) وغير المقروءة.
    إذا يوجد doctor_seen_at → نعد فقط doctor_seen_at IS NULL
    إذا غير موجود → نعد كل READY.
    """
    qs = LabOrder.objects.filter(doctor=doctor, status=LabOrder.Status.READY)
    if _has_order_field("doctor_seen_at"):
        qs = qs.filter(doctor_seen_at__isnull=True)
    return qs.count()


def _doctor_kpis(doctor: Doctor) -> dict[str, int]:
    """
    ✅ أرقام ثابتة للطبيب (لا تعتمد على التبويب الحالي بالـ inbox)
    """
    today = timezone.localdate()
    base = LabOrder.objects.filter(doctor=doctor)

    completed_results = base.filter(status=LabOrder.Status.READY).count()

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

    doctor = _get_doctor_profile(request.user)
    if not doctor:
        return JsonResponse({"count": 0})

    return JsonResponse({"count": _doctor_ready_count(doctor)})


# ------------------------------------------------------------
# Lab Dashboard (LAB ONLY)
# ------------------------------------------------------------
@login_required
def lab_dashboard(request: HttpRequest) -> HttpResponse:
    if not is_lab(request.user):
        return _deny_lab_area(request)

    today = timezone.localdate()
    settings_obj = _get_lab_settings()

    status_filter = (request.GET.get("status", "") or "").strip().upper()
    q = (request.GET.get("q", "") or "").strip()

    base_qs = LabOrder.objects.select_related("patient", "doctor__user").all()
    if status_filter in ORDER_STATUSES:
        base_qs = base_qs.filter(status=status_filter)

    if q:
        try:
            base_qs = base_qs.filter(_laborder_text_search_q(q))
        except FieldError:
            base_qs = base_qs.filter(_laborder_text_search_q_basic(q))

    qs_all = LabOrder.objects.all()

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
        LabOrder.objects.select_related("patient", "doctor__user")
        .order_by("-created_at")[:12]
    )

    start_week = today - timedelta(days=today.weekday())
    end_week = start_week + timedelta(days=6)
    labels = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    days = [start_week + timedelta(days=i) for i in range(7)]

    week_counts = dict(
        LabOrder.objects
        .filter(created_at__date__gte=start_week, created_at__date__lte=end_week)
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
    }
    return render(request, "lab/lab_dashboard.html", context)


# ------------------------------------------------------------
# Lab Settings (LAB ONLY)
# ------------------------------------------------------------
@login_required
def lab_settings(request: HttpRequest) -> HttpResponse:
    if not is_lab(request.user):
        return _deny_lab_area(request)

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

    return render(request, "lab/lab_settings.html", {"form": form, "settings_obj": obj})


# ------------------------------------------------------------
# Doctor views (DOCTOR ONLY)
# ------------------------------------------------------------
@login_required
def doctor_orders_inbox(request: HttpRequest) -> HttpResponse:
    if not is_doctor(request.user):
        return _deny_doctor_area(request)

    doctor = _get_doctor_profile(request.user)
    if not doctor:
        messages.error(request, "لا يوجد ملف Doctor مرتبط بهذا المستخدم.")
        return _try_redirect("doctor:dashboard", fallback_name="home:index")

    ready_count = _doctor_ready_count(doctor)
    doctor_stats = _doctor_kpis(doctor)

    status = (request.GET.get("status", LabOrder.Status.PENDING) or "").strip().upper()
    if status not in ORDER_STATUSES:
        status = LabOrder.Status.PENDING

    q = (request.GET.get("q", "") or "").strip()

    qs = (
        LabOrder.objects.select_related("patient", "doctor__user")
        .filter(doctor=doctor, status=status)
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
        },
    )


@login_required
def doctor_create_lab_order(request: HttpRequest, patient_id: int | None = None) -> HttpResponse:
    if not is_doctor(request.user):
        return _deny_doctor_area(request)

    doctor = _get_doctor_profile(request.user)
    if not doctor:
        messages.error(request, "لا يوجد ملف Doctor مرتبط بهذا المستخدم.")
        return _try_redirect("doctor:dashboard", fallback_name="home:index")

    ready_count = _doctor_ready_count(doctor)

    patient: Optional[Patient] = None
    if patient_id is not None:
        patient = get_object_or_404(Patient, pk=patient_id)

        if _enforce_doctor_patient_scope() and not _doctor_can_access_patient(doctor, patient):
            messages.error(request, "هذا المريض خارج نطاق هذا الطبيب.")
            return _try_redirect("lab:doctor_orders_inbox", fallback_name="doctor:dashboard")

    form = LabOrderCreateForm(request.POST or None, request.FILES or None)
    _configure_doctor_order_form(form, doctor, patient=patient)

    if request.method == "POST":
        if form.is_valid():
            order: LabOrder = form.save(commit=False)

            # 1) إذا المريض محدد من الرابط، نستخدمه مباشرة
            if patient is not None:
                order.patient = patient

            # 2) إذا ماكو patient، نستنتجه من appointment
            if not getattr(order, "patient_id", None):
                inferred = _infer_patient_from_order(order)
                if inferred is not None:
                    if _enforce_doctor_patient_scope() and not _doctor_can_access_patient(doctor, inferred):
                        form.add_error("appointment", "هذا الموعد يخص مريضًا خارج نطاق هذا الطبيب.")
                        messages.error(request, "هذا المريض خارج نطاق هذا الطبيب.")
                        return render(
                            request,
                            "lab/doctor_create_order.html",
                            {"form": form, "patient": patient, "ready_count": ready_count},
                        )
                    order.patient = inferred

            # 3) لازم يصير عندنا patient بالنهاية
            if not getattr(order, "patient_id", None):
                if "appointment" in form.fields:
                    form.add_error("appointment", "اختاري Appointment صالحًا يحتوي على مريض.")
                messages.error(request, "رجاءً اختاري موعدًا صالحًا قبل إنشاء طلب المختبر.")
                return render(
                    request,
                    "lab/doctor_create_order.html",
                    {"form": form, "patient": patient, "ready_count": ready_count},
                )

            # 4) إذا انختار appointment، لازم يخص نفس الطبيب
            if not _appointment_belongs_to_doctor(order, doctor):
                if "appointment" in form.fields:
                    form.add_error("appointment", "الـ Appointment المختار لا يخص هذا الطبيب.")
                messages.error(request, "الـ Appointment المختار لا يخص هذا الطبيب.")
                return render(
                    request,
                    "lab/doctor_create_order.html",
                    {"form": form, "patient": patient, "ready_count": ready_count},
                )

            order.doctor = doctor
            order.status = LabOrder.Status.PENDING

            if _has_order_field("requested_tests_text"):
                order.requested_tests_text = (getattr(order, "requested_tests_text", "") or "").strip()
            if _has_order_field("notes"):
                order.notes = (getattr(order, "notes", "") or "").strip()

            order.save()
            messages.success(request, "✅ تم إرسال طلب المختبر.")
            return redirect("lab:doctor_order_detail", order_id=order.id)

        messages.error(request, "❌ تأكدي من الحقول.")

    return render(
        request,
        "lab/doctor_create_order.html",
        {"form": form, "patient": patient, "ready_count": ready_count},
    )


@login_required
def doctor_order_detail(request: HttpRequest, order_id: int) -> HttpResponse:
    if not is_doctor(request.user):
        return _deny_doctor_area(request)

    doctor = _get_doctor_profile(request.user)
    if not doctor:
        messages.error(request, "لا يوجد ملف Doctor مرتبط بهذا المستخدم.")
        return _try_redirect("doctor:dashboard", fallback_name="home:index")

    order = get_object_or_404(
        LabOrder.objects.select_related("patient", "doctor__user", "appointment"),
        pk=order_id,
        doctor=doctor,
    )

    _mark_seen_by_doctor_if_ready(order)

    ready_count = _doctor_ready_count(doctor)
    result = LabResult.objects.filter(order=order).first()

    return render(
        request,
        "lab/doctor_order_detail.html",
        {"order": order, "result": result, "ready_count": ready_count},
    )


# ------------------------------------------------------------
# Lab views (LAB ONLY)
# ------------------------------------------------------------
@login_required
def lab_inbox(request: HttpRequest) -> HttpResponse:
    if not is_lab(request.user):
        return _deny_lab_area(request)

    settings_obj = _get_lab_settings()

    status = (request.GET.get("status", LabOrder.Status.PENDING) or "").strip().upper()
    if status not in ORDER_STATUSES:
        status = LabOrder.Status.PENDING

    q = (request.GET.get("q", "") or "").strip()

    qs = (
        LabOrder.objects.select_related("patient", "doctor__user")
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
        {"orders": qs, "status": status, "q": q, "settings_obj": settings_obj},
    )


@login_required
def lab_order_detail(request: HttpRequest, order_id: int) -> HttpResponse:
    """
    Lab staff can view a specific order and create/edit/verify results.
    Respects LabSettings.require_verify_before_ready

    ✅ Guard:
    - إذا الطلب CANCELLED: ما نسمح بتعديل/إرسال نتائج
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

    order = get_object_or_404(
        LabOrder.objects.select_related("patient", "doctor__user", "appointment"),
        pk=order_id,
    )

    settings_obj = _get_lab_settings()
    require_verify = bool(getattr(settings_obj, "require_verify_before_ready", True))

    if request.method == "GET":
        _mark_order_seen_if_pending(order, request.user)

    result, _ = LabResult.objects.get_or_create(order=order)

    if request.method == "POST":
        if order.status == LabOrder.Status.CANCELLED:
            messages.error(request, "❌ This order is cancelled and cannot be updated or sent.")
            return redirect("lab:lab_order_detail", order_id=order.id)

        form = _build_result_form(request=request, instance=result, settings_obj=settings_obj)
        action = _normalize_action(request.POST.get("action", "save"))

        if form.is_valid():
            form.save()

            with transaction.atomic():
                if action == "verify":
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
        form = _build_result_form(request=request, instance=result, settings_obj=settings_obj)

    return render(
        request,
        "lab/lab_order_detail.html",
        {
            "order": order,
            "form": form,
            "result": result,
            "settings_obj": settings_obj,
            "require_verify": require_verify,
        },
    )