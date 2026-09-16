from __future__ import annotations

from datetime import timedelta
from typing import Any
from urllib.parse import urlencode

from django.contrib.auth.decorators import login_required
from django.core.cache import cache
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db.models import Count, Min, Q, Sum
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from django.views.decorators.http import require_GET

from appointments.models import Appointment, AppointmentStatus
from hospital.models import StaffAssignment
from hospital.models import Branch, Hospital

from .services import build_dashboard_analytics


DEFAULT_ANALYSIS_DAYS = 30
MIN_ANALYSIS_DAYS = 7
MAX_ANALYSIS_DAYS = 365
CACHE_DURATION_SECONDS = 60
CACHE_NAMESPACE = "clinichub:central-analytics:v3"
BRANCH_DETAIL_PAGE_SIZE = 25


def _hospital_admin_assignments(user):
    """
    Return active hospital-admin assignments for one user.
    """
    return StaffAssignment.objects.filter(
        user=user,
        role=StaffAssignment.Roles.HOSPITAL_ADMIN,
        is_active=True,
        hospital__is_active=True,
    )


def _accessible_hospitals(user):
    """
    Return hospitals visible to the analytics user.
    """
    hospitals = Hospital.objects.filter(
        is_active=True,
    )

    if user.is_superuser:
        return hospitals

    if getattr(user, "role", None) != "admin":
        return hospitals.none()

    hospital_ids = _hospital_admin_assignments(
        user
    ).values_list(
        "hospital_id",
        flat=True,
    )

    return hospitals.filter(
        pk__in=hospital_ids,
    ).distinct()


def _ensure_admin_access(request) -> None:
    """
    Permit platform superusers and assigned hospital admins only.
    """
    user = request.user

    if user.is_superuser:
        return

    if (
        getattr(user, "role", None) != "admin"
        or not _hospital_admin_assignments(user).exists()
    ):
        raise PermissionDenied(
            "Only assigned hospital administrators "
            "can access analytics pages."
        )


def _get_analysis_days(request) -> int:
    """
    قراءة مدة التحليل وحصرها بين أسبوع وسنة.
    """
    try:
        days = int(
            request.GET.get(
                "days",
                DEFAULT_ANALYSIS_DAYS,
            )
        )
    except (TypeError, ValueError):
        days = DEFAULT_ANALYSIS_DAYS

    return max(
        MIN_ANALYSIS_DAYS,
        min(days, MAX_ANALYSIS_DAYS),
    )


def _get_query_value(
    request,
    name: str,
) -> str:
    """
    قراءة قيمة نصية آمنة من Query String.
    """
    value = request.GET.get(name, "")

    if value is None:
        return ""

    return str(value).strip()


def _find_by_pk(
    queryset,
    raw_pk: str,
):
    """
    البحث الآمن بالمفتاح الأساسي.
    """
    if not raw_pk:
        return None

    try:
        return queryset.filter(
            pk=raw_pk,
        ).first()
    except (
        TypeError,
        ValueError,
        OverflowError,
    ):
        return None


def _empty_appointment_stats() -> dict[str, Any]:
    """
    مؤشرات افتراضية عند عدم وجود بيانات.
    """
    return {
        "total": 0,
        "pending": 0,
        "completed": 0,
        "cancelled": 0,
        "unique_patients": 0,
        "revenue": 0,
    }


def _build_cache_key(
    *,
    hospital_id: Any,
    branch_id: Any | None,
    days: int,
    today,
) -> str:
    """
    إنشاء مفتاح مستقل لكل مؤسسة وفرع وفترة.
    """
    branch_token = (
        str(branch_id)
        if branch_id is not None
        else "all"
    )

    return (
        f"{CACHE_NAMESPACE}:"
        f"hospital:{hospital_id}:"
        f"branch:{branch_token}:"
        f"days:{days}:"
        f"date:{today.isoformat()}"
    )


def _calculate_percentage(
    part: int,
    total: int,
) -> float:
    """
    حساب النسبة المئوية بصورة آمنة.
    """
    if total <= 0:
        return 0.0

    return round(
        (part / total) * 100,
        1,
    )


def _build_branch_action_plan(
    *,
    overdue_count: int,
    max_days_overdue: int,
) -> dict[str, str]:
    """
    تحديد مستوى الأولوية والتوصية الإدارية.
    """
    if overdue_count <= 0:
        return {
            "level": "healthy",
            "label": "مستقر",
            "title": "لا توجد مواعيد متأخرة",
            "recommendation": (
                "استمر بمتابعة المواعيد اليومية والمحافظة "
                "على سرعة إغلاق الحالات."
            ),
        }

    if max_days_overdue >= 14 or overdue_count >= 10:
        return {
            "level": "critical",
            "label": "حرج",
            "title": "تدخل إداري فوري",
            "recommendation": (
                "تواصل فوراً مع المرضى، وحدد مسؤولاً لمراجعة "
                "المواعيد المتأخرة وإغلاقها أو إعادة جدولتها اليوم."
            ),
        }

    if max_days_overdue >= 7 or overdue_count >= 5:
        return {
            "level": "warning",
            "label": "يحتاج متابعة",
            "title": "خطة معالجة خلال 24 ساعة",
            "recommendation": (
                "وزع الحالات على الموظفين واتصل بالمرضى، "
                "ثم حدث حالة كل موعد قبل نهاية يوم العمل."
            ),
        }

    return {
        "level": "attention",
        "label": "تنبيه",
        "title": "مراجعة تشغيلية",
        "recommendation": (
            "راجع الحالات المتأخرة وحدّث حالتها أو أعد "
            "جدولتها لمنع تراكمها."
        ),
    }


@login_required
@require_GET
def dashboard(request):
    """
    لوحة القيادة المركزية لمراقبة المؤسسات والفروع.
    """
    _ensure_admin_access(request)

    today = timezone.localdate()
    selected_days = _get_analysis_days(request)

    hospitals = _accessible_hospitals(
        request.user
    ).order_by(
        "name",
        "pk",
    )

    hospital_value = _get_query_value(
        request,
        "hospital",
    )

    selected_hospital = _find_by_pk(
        hospitals,
        hospital_value,
    )

    if selected_hospital is None:
        selected_hospital = hospitals.first()

    branches = Branch.objects.none()
    analysis_branches = Branch.objects.none()
    selected_branch = None
    appointment_stats = _empty_appointment_stats()
    analytics_data = None

    if selected_hospital:
        branches = Branch.objects.filter(
            hospital=selected_hospital,
            is_active=True,
        ).order_by(
            "name",
            "pk",
        )

        branch_value = _get_query_value(
            request,
            "branch",
        )

        if branch_value.lower() not in {
            "",
            "all",
            "0",
        }:
            selected_branch = _find_by_pk(
                branches,
                branch_value,
            )

        if selected_branch:
            analysis_branches = branches.filter(
                pk=selected_branch.pk,
            )
        else:
            analysis_branches = branches

        today_appointments = Appointment.objects.filter(
            branch__in=analysis_branches,
            scheduled_day=today,
        )

        appointment_stats = today_appointments.aggregate(
            total=Count("pk"),

            pending=Count(
                "pk",
                filter=Q(
                    status=AppointmentStatus.PENDING,
                ),
            ),

            completed=Count(
                "pk",
                filter=Q(
                    status=AppointmentStatus.COMPLETED,
                ),
            ),

            cancelled=Count(
                "pk",
                filter=Q(
                    status=AppointmentStatus.CANCELLED,
                ),
            ),

            unique_patients=Count(
                "patient_id",
                distinct=True,
            ),

            revenue=Sum(
                "iqd_amount",
                filter=Q(
                    status=AppointmentStatus.COMPLETED,
                ),
            ),
        )

        for key in (
            "total",
            "pending",
            "completed",
            "cancelled",
            "unique_patients",
        ):
            appointment_stats[key] = int(
                appointment_stats.get(key) or 0
            )

        appointment_stats["revenue"] = (
            appointment_stats.get("revenue") or 0
        )

        cache_key = _build_cache_key(
            hospital_id=selected_hospital.pk,
            branch_id=(
                selected_branch.pk
                if selected_branch
                else None
            ),
            days=selected_days,
            today=today,
        )

        force_refresh = (
            _get_query_value(
                request,
                "refresh",
            ) == "1"
        )

        if not force_refresh:
            analytics_data = cache.get(
                cache_key,
            )

        if analytics_data is None:
            analytics_data = build_dashboard_analytics(
                hospital=selected_hospital,
                branch=selected_branch,
                days=selected_days,
            )

            cache.set(
                cache_key,
                analytics_data,
                CACHE_DURATION_SECONDS,
            )

    total_hospitals = hospitals.count()
    active_branches = branches.count()

    if selected_hospital:
        if selected_branch:
            analysis_scope_label = (
                f"{selected_hospital.name} — "
                f"{selected_branch.name}"
            )
        else:
            analysis_scope_label = (
                f"{selected_hospital.name} — جميع الفروع"
            )
    else:
        analysis_scope_label = "لا توجد مؤسسة محددة"

    context = {
        "today": today,
        "hospitals": hospitals,
        "selected_hospital": selected_hospital,
        "selected_days": selected_days,
        "branches": branches,
        "selected_branch": selected_branch,

        "selected_branch_value": (
            selected_branch.pk
            if selected_branch
            else "all"
        ),

        "analysis_scope_label": analysis_scope_label,
        "total_hospitals": total_hospitals,
        "active_branches": active_branches,

        "filtered_branch_count": (
            1
            if selected_branch
            else active_branches
        ),

        "appointment_stats": appointment_stats,
        "analytics": analytics_data,

        "chart_data": (
            analytics_data.get(
                "charts",
                {},
            )
            if analytics_data
            else {}
        ),

        "branch_analytics": (
            analytics_data.get(
                "branches",
                [],
            )
            if analytics_data
            else []
        ),

        "smart_insights": (
            analytics_data.get(
                "insights",
                [],
            )
            if analytics_data
            else []
        ),
    }

    return render(
        request,
        "analytics/dashboard.html",
        context,
    )


@login_required
@require_GET
def branch_detail(
    request,
    branch_id: int,
):
    """
    صفحة التفاصيل التنفيذية لفرع محدد.

    تعرض:
    - مؤشرات الفترة.
    - المواعيد المتأخرة.
    - عدد المرضى المتأثرين.
    - مستوى الخطورة.
    - التوصية الإدارية.
    - Pagination لمنع تحميل البيانات الكبيرة.
    """
    _ensure_admin_access(request)

    today = timezone.localdate()
    selected_days = _get_analysis_days(request)

    start_date = today - timedelta(
        days=selected_days - 1,
    )

    accessible_hospitals = _accessible_hospitals(
        request.user
    )

    branch = get_object_or_404(
        Branch.objects.select_related(
            "hospital",
        ).filter(
            hospital__in=accessible_hospitals,
        ),
        pk=branch_id,
        is_active=True,
        hospital__is_active=True,
    )

    period_appointments = Appointment.objects.filter(
        branch=branch,
        scheduled_day__gte=start_date,
        scheduled_day__lte=today,
    )

    period_stats = period_appointments.aggregate(
        total=Count("pk"),

        pending=Count(
            "pk",
            filter=Q(
                status=AppointmentStatus.PENDING,
            ),
        ),

        completed=Count(
            "pk",
            filter=Q(
                status=AppointmentStatus.COMPLETED,
            ),
        ),

        cancelled=Count(
            "pk",
            filter=Q(
                status=AppointmentStatus.CANCELLED,
            ),
        ),

        unique_patients=Count(
            "patient_id",
            distinct=True,
        ),

        revenue=Sum(
            "iqd_amount",
            filter=Q(
                status=AppointmentStatus.COMPLETED,
            ),
        ),
    )

    for key in (
        "total",
        "pending",
        "completed",
        "cancelled",
        "unique_patients",
    ):
        period_stats[key] = int(
            period_stats.get(key) or 0
        )

    period_stats["revenue"] = (
        period_stats.get("revenue") or 0
    )

    period_stats["completion_rate"] = (
        _calculate_percentage(
            period_stats["completed"],
            period_stats["total"],
        )
    )

    period_stats["cancellation_rate"] = (
        _calculate_percentage(
            period_stats["cancelled"],
            period_stats["total"],
        )
    )

    overdue_appointments = (
        period_appointments.filter(
            status=AppointmentStatus.PENDING,
            scheduled_day__lt=today,
        )
        .select_related(
            "patient",
            "doctor",
        )
        .order_by(
            "scheduled_day",
            "scheduled_time",
            "pk",
        )
    )

    overdue_stats = overdue_appointments.aggregate(
        total=Count("pk"),

        unique_patients=Count(
            "patient_id",
            distinct=True,
        ),

        oldest_date=Min(
            "scheduled_day",
        ),
    )

    overdue_count = int(
        overdue_stats.get("total") or 0
    )

    overdue_unique_patients = int(
        overdue_stats.get("unique_patients") or 0
    )

    oldest_overdue_date = overdue_stats.get(
        "oldest_date"
    )

    if oldest_overdue_date:
        max_days_overdue = max(
            (
                today - oldest_overdue_date
            ).days,
            0,
        )
    else:
        max_days_overdue = 0

    pending_today = Appointment.objects.filter(
        branch=branch,
        status=AppointmentStatus.PENDING,
        scheduled_day=today,
    ).count()

    paginator = Paginator(
        overdue_appointments,
        BRANCH_DETAIL_PAGE_SIZE,
    )

    page_obj = paginator.get_page(
        request.GET.get("page"),
    )

    for appointment in page_obj.object_list:
        appointment.days_overdue = max(
            (
                today
                - appointment.scheduled_day
            ).days,
            0,
        )

        if appointment.days_overdue >= 14:
            appointment.delay_level = "critical"
            appointment.delay_label = "حرج"

        elif appointment.days_overdue >= 7:
            appointment.delay_level = "warning"
            appointment.delay_label = "مرتفع"

        else:
            appointment.delay_level = "attention"
            appointment.delay_label = "متوسط"

    action_plan = _build_branch_action_plan(
        overdue_count=overdue_count,
        max_days_overdue=max_days_overdue,
    )

    dashboard_query = urlencode(
        {
            "hospital": branch.hospital_id,
            "branch": branch.pk,
            "days": selected_days,
        }
    )

    pagination_query = urlencode(
        {
            "days": selected_days,
        }
    )

    context = {
        "today": today,
        "start_date": start_date,
        "selected_days": selected_days,

        "hospital": branch.hospital,
        "branch": branch,

        "period_stats": period_stats,

        "overdue_count": overdue_count,
        "overdue_unique_patients": (
            overdue_unique_patients
        ),

        "oldest_overdue_date": (
            oldest_overdue_date
        ),

        "max_days_overdue": max_days_overdue,
        "pending_today": pending_today,

        "action_plan": action_plan,
        "page_obj": page_obj,

        "dashboard_query": dashboard_query,
        "pagination_query": pagination_query,
    }

    return render(
        request,
        "analytics/branch_detail.html",
        context,
    )