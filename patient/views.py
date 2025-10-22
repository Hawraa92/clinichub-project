"""
patient/views.py
Refactor 06-Aug-2025 — متوافق مع نموذج Patient و services
- إزالة Save & Edit من الإضافة (create)
- تحويل السكرتير بعد الإضافة إلى قائمة المرضى، والدكتور إلى صفحة التفاصيل
- فرز أسماء غير حساس لحالة الأحرف
- حساب الثقة من prediction_proba على نحو مرن
- دعم كلٍّ من user.patient_profile و user.patient
- إصلاح كشف مجموعات الصلاحيات (Doctors / Secretaries)
"""

from __future__ import annotations

import json
from datetime import timedelta, datetime, date
from typing import Final, Optional

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required, user_passes_test
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

# نماذج مرتبطة بالداشبورد
from appointments.models import Appointment
from prescription.models import Prescription

# الفواتير (اختياري)
try:
    from billing.models import Invoice  # يتوقع وجود علاقة patient أو appointment__patient
    HAS_BILLING = True
except Exception:
    Invoice = None  # type: ignore
    HAS_BILLING = False

PAGE_SIZE: Final[int] = getattr(settings, "PATIENT_LIST_PAGE_SIZE", 25)


# ------------------------------------------------------------------ #
#                       Role-helper utilities                         #
# ------------------------------------------------------------------ #

GROUPS_MAP = {
    "doctor": "Doctors",
    "secretary": "Secretaries",
}

def _has_role(user, role_name: str) -> bool:
    """
    يدعم user.role ومجموعات Django:
    'doctor' -> 'Doctors', 'secretary' -> 'Secretaries'
    """
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
    # دعم كلا الاسمين: patient_profile أو patient
    return hasattr(user, "patient_profile") or hasattr(user, "patient")

def is_med_staff(user) -> bool:  # noqa: ANN001
    return is_doctor(user) or is_secretary(user)

doctor_required = user_passes_test(is_doctor)
secretary_required = user_passes_test(is_secretary)
med_staff_required = user_passes_test(is_med_staff)
patient_required = user_passes_test(is_patient)


def _current_doctor_for(user) -> Optional["doctor.Doctor"]:  # type: ignore[name-defined]
    """
    يجلب كيان Doctor المرتبط بالمستخدم (إن وُجد) لتعبئته تلقائيًا في النماذج.
    """
    try:
        from doctor.models import Doctor  # import متأخر لتجنّب الدورات
        qs = Doctor.objects.select_related("user").filter(user=user)
        # لو عندك حقل available/ is_available
        if hasattr(Doctor, "available"):
            qs = qs.filter(available=True)
        elif hasattr(Doctor, "is_available"):
            qs = qs.filter(is_available=True)
        return qs.first()
    except Exception:
        return None


# ------------------------------------------------------------------ #
#                              Create                                #
# ------------------------------------------------------------------ #
@login_required
@med_staff_required
@require_http_methods(["GET", "POST"])
def create_patient(request):
    """
    إنشاء مريض جديد:
    - الطبيب يستخدم DoctorPatientForm ويُشغِّل التنبؤ بعد الحفظ.
    - السكرتير يستخدم SecretaryPatientForm بدون تشغيل التنبؤ.
    - للطبيب: تعيين الطبيب الحالي تلقائيًا إذا لم يُحدَّد في النموذج.
    - بعد الحفظ: السكرتير -> قائمة المرضى، الطبيب -> صفحة التفاصيل.
    """
    FormClass = DoctorPatientForm if is_doctor(request.user) else SecretaryPatientForm

    initial = {}
    if is_doctor(request.user):
        doc = _current_doctor_for(request.user)
        if doc:
            initial["doctor"] = doc

    form = FormClass(request.POST or None, initial=initial)

    if request.method == "POST":
        if form.is_valid():
            patient: Patient = form.save(commit=False)

            # للطبيب: تأكّد من تعيين الطبيب الحالي إذا كان الحقل فارغًا
            if is_doctor(request.user) and not getattr(patient, "doctor", None):
                doc = _current_doctor_for(request.user)
                if doc:
                    patient.doctor = doc

            # حفظ
            patient.save()

            # تشغيل التنبؤ للطبيب فقط (مع التقاط الأخطاء)
            if is_doctor(request.user):
                try:
                    from patient.services import predict_and_save  # import متأخر
                    predict_and_save(patient)
                except Exception:
                    messages.warning(
                        request,
                        _("Patient saved, but AI prediction could not run right now."),
                    )

            messages.success(request, _("Patient created successfully."))

            # إعادة التوجيه بعد الحفظ
            if is_secretary(request.user):
                return redirect("patient:list")
            return redirect("patient:detail", pk=patient.pk)

        messages.error(request, _("Please correct the errors below."))

    return render(request, "patient/create_patient.html", {"form": form})


# ------------------------------------------------------------------ #
#                               List                                 #
# ------------------------------------------------------------------ #
@login_required
@med_staff_required
@require_http_methods(["GET"])
def patient_list(request):
    """
    قائمة المرضى للطاقم الطبي مع بحث وفلترة وترتيب وترقيم صفحات.
    دعم البحث بالاسم/الهاتف/الإيميل.
    """
    search_query = (request.GET.get("q") or "").strip()
    statuses = request.GET.getlist("status")
    sexes = request.GET.getlist("sex")
    sort_key = request.GET.get("sort", "recent")

    qs = Patient.objects.select_related("doctor", "doctor__user")

    # — البحث —
    if search_query:
        qs = qs.filter(
            Q(full_name__icontains=search_query)
            | Q(mobile__icontains=search_query)
            | Q(email__icontains=search_query)
        )

    # — فلترة الحالة —
    allowed_status = {int(code) for code, _ in DiabetesStatus.choices}
    try:
        statuses_int = [int(s) for s in statuses if int(s) in allowed_status]
    except ValueError:
        statuses_int = []
    if statuses_int:
        qs = qs.filter(diabetes_status__in=statuses_int)

    # — فلترة الجنس —
    try:
        sex_choices = Patient._meta.get_field("sex").choices
        allowed_sex = {choice[0] for choice in sex_choices} if sex_choices else set()
    except Exception:
        allowed_sex = set()
    sexes = [s for s in sexes if s in allowed_sex]
    if sexes:
        qs = qs.filter(sex__in=sexes)

    # — الترتيب —
    sort_map = {
        "name_asc": Lower("full_name").asc(),
        "name_desc": Lower("full_name").desc(),
        "status": "diabetes_status",
        "recent": "-created_at",
    }
    order_by = sort_map.get(sort_key, "-created_at")
    qs = qs.order_by(order_by)

    # — إحصاءات سريعة —
    diabetic_count = qs.filter(diabetes_status=DiabetesStatus.DIABETIC).count()
    new_this_week = qs.filter(created_at__gte=timezone.now() - timedelta(days=7)).count()

    # — ترقيم الصفحات —
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
    }
    return render(request, "patient/patient_list.html", context)


# ------------------------------------------------------------------ #
#                              Detail                                #
# ------------------------------------------------------------------ #
@login_required
@med_staff_required
@require_http_methods(["GET"])
def patient_detail(request, pk: int):
    """
    صفحة التفاصيل: تعرض المريض + مؤشر الثقة إن وُجد تنبؤ.
    الثقة تُحسب من:
      - احتمال الفئة المتنبأ بها diabetes_prediction إذا وُجدت،
      - وإلا أعلى احتمال من prediction_proba.
    """
    patient: Patient = get_object_or_404(
        Patient.objects.select_related("doctor", "doctor__user"),
        pk=pk,
    )

    confidence_pct = None
    confidence_angle = None

    proba = getattr(patient, "prediction_proba", {}) or {}
    if proba and isinstance(proba, dict):
        # اختر الفئة المستهدفة لحساب الثقة
        if getattr(patient, "diabetes_prediction", None) is not None:
            target = str(int(patient.diabetes_prediction))
        else:
            try:
                target = max(proba.keys(), key=lambda k: float(proba[k]))
            except Exception:
                target = None

        if target is not None and target in proba:
            try:
                confidence_pct = int(round(100 * float(proba[target])))
                confidence_angle = confidence_pct * 180 / 100
            except Exception:
                confidence_pct = None
                confidence_angle = None

    return render(
        request,
        "patient/patient_detail.html",
        {
            "patient": patient,
            "confidence": confidence_pct,
            "confidence_angle": confidence_angle,
        },
    )


# ------------------------------------------------------------------ #
#                               Edit                                 #
# ------------------------------------------------------------------ #
@login_required
@med_staff_required
@require_http_methods(["GET", "POST"])
def edit_patient(request, pk: int):
    """
    تعديل بيانات مريض (الطاقم الطبي فقط).
    - للطبيب: إعادة تشغيل التنبؤ بعد الحفظ (مع التقاط الأخطاء).
    """
    patient: Patient = get_object_or_404(
        Patient.objects.select_related("doctor", "doctor__user"),
        pk=pk,
    )

    FormClass = DoctorPatientForm if is_doctor(request.user) else SecretaryPatientForm
    form = FormClass(request.POST or None, instance=patient)

    if request.method == "POST":
        if form.is_valid():
            patient = form.save(commit=False)

            # للطبيب: تأكّد من تعيين الطبيب الحالي إذا كان مناسبًا
            if is_doctor(request.user) and not getattr(patient, "doctor", None):
                doc = _current_doctor_for(request.user)
                if doc:
                    patient.doctor = doc

            patient.save()

            if is_doctor(request.user):
                try:
                    from patient.services import predict_and_save  # import متأخر
                    predict_and_save(patient)
                except Exception:
                    messages.warning(
                        request,
                        _("Patient saved, but AI prediction could not run right now."),
                    )

            messages.success(request, _("Patient updated successfully."))
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


# ------------------------------------------------------------------ #
#                      Helpers: Weekly chart data                     #
# ------------------------------------------------------------------ #

def _week_labels_counts(start: date, end: date, qs):
    """
    يبني بيانات الرسم الأسبوعي لهذا المريض: labels (Mon..Sun) و data (counts).
    يعتمد على scheduled_time (DATE).
    """
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
        labels.append(cur.strftime("%a"))  # Mon, Tue, ...
        data.append(gmap.get(cur, 0))
        cur += timedelta(days=1)
    return labels, data


# ------------------------------------------------------------------ #
#                           Patient Dashboard                         #
# ------------------------------------------------------------------ #
@login_required
@patient_required
@require_http_methods(["GET"])
def patient_dashboard(request):
    """
    لوحة المريض لعرض بياناته الشخصية والتنبيهات (عند دخول المريض ذاته).
    - يعيد قالب: templates/patient/dashboard.html
    - يمرر كونتكست واقعي: مواعيد قادمة، وصفات حديثة، فواتير، ورسم أسبوعي للزيارات.
    """
    patient_obj = getattr(request.user, "patient_profile", None) or getattr(request.user, "patient", None)
    if not patient_obj:
        raise PermissionDenied

    now = timezone.now()
    today = timezone.localdate()
    start_week = today - timedelta(days=6)  # آخر 7 أيام شاملاً اليوم
    end_week = today

    # --- المواعيد القادمة ---
    upcoming_qs = (
        Appointment.objects.select_related("doctor__user", "patient")
        .filter(patient=patient_obj, scheduled_time__gte=now)
        .exclude(status__iexact="cancelled")
        .order_by("scheduled_time")
    )
    upcoming_appointments = list(upcoming_qs[:10])
    next_appointment = upcoming_appointments[0] if upcoming_appointments else None

    # --- الرسم الأسبوعي لزيارات المريض ---
    week_qs = Appointment.objects.filter(
        patient=patient_obj,
        scheduled_time__date__gte=start_week,
        scheduled_time__date__lte=end_week,
    )
    labels, counts = _week_labels_counts(start_week, end_week, week_qs)
    chart_data_json = json.dumps({"labels": labels, "data": counts})

    # --- الوصفات الحديثة ---
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

    # --- الفواتير (اختياري) ---
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

    # --- اكتمال الملف الشخصي ---
    profile_completion = getattr(patient_obj, "profile_completion", None)
    if profile_completion is None:
        # تقدير مبسّط
        candidate_fields = [
            "full_name", "phone", "date_of_birth", "address",
            "gender", "blood_type", "emergency_contact",
        ]
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
