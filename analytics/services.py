from __future__ import annotations

from datetime import timedelta
from typing import Any

from django.db.models import Count, Q, Sum
from django.utils import timezone

from appointments.models import Appointment, AppointmentStatus
from hospital.models import Branch


MIN_ANALYTICS_DAYS = 7
MAX_ANALYTICS_DAYS = 365


def _as_int(value: Any) -> int:
    """تحويل نتائج التجميع إلى عدد صحيح آمن."""
    return int(value or 0)


def _as_float(value: Any) -> float:
    """تحويل القيم المالية إلى رقم صالح للإرسال إلى Chart.js."""
    return float(value or 0)


def _percentage(
    part: int | float,
    total: int | float,
) -> float:
    """حساب النسبة المئوية مع تجنب القسمة على صفر."""
    if not total:
        return 0.0

    return round((part / total) * 100, 1)


def _normalise_days(days: Any) -> int:
    """حصر مدة التحليل بين 7 أيام وسنة واحدة."""
    try:
        parsed_days = int(days)
    except (TypeError, ValueError):
        parsed_days = 30

    return max(
        MIN_ANALYTICS_DAYS,
        min(parsed_days, MAX_ANALYTICS_DAYS),
    )


def _evaluate_branch_health(
    *,
    total: int,
    completed: int,
    pending: int,
    cancelled: int,
    overdue_pending: int,
    today_pending: int,
) -> dict[str, Any]:
    """
    تقييم الصحة التشغيلية للفرع.

    لا تُعد مواعيد اليوم المتبقية مواعيد متأخرة؛ لذلك يعتمد
    التقييم على المواعيد المنجزة والملغاة والمعلقة التي تجاوزت
    تاريخها فقط.
    """
    if total == 0:
        return {
            "key": "quiet",
            "label": "لا توجد حركة",
            "score": None,
            "reason": "لم تُسجل مواعيد خلال الفترة المختارة.",
            "recommendation": (
                "تحقق من نشاط الفرع أو من صحة ربط بياناته."
            ),
            "due_total": 0,
            "due_completion_rate": 0.0,
            "overdue_rate": 0.0,
        }

    due_total = (
        completed
        + cancelled
        + overdue_pending
    )

    if due_total == 0:
        return {
            "key": "healthy",
            "label": "تشغيل طبيعي",
            "score": 100,
            "reason": (
                f"يوجد {today_pending} موعد قيد الانتظار اليوم، "
                "ولا توجد مواعيد متأخرة."
            ),
            "recommendation": (
                "استمر بمتابعة مواعيد اليوم ضمن سير العمل المعتاد."
            ),
            "due_total": 0,
            "due_completion_rate": 0.0,
            "overdue_rate": 0.0,
        }

    due_completion_rate = _percentage(
        completed,
        due_total,
    )
    overdue_rate = _percentage(
        overdue_pending,
        due_total,
    )
    due_cancellation_rate = _percentage(
        cancelled,
        due_total,
    )

    score = 100.0
    score -= min(overdue_rate * 0.65, 50.0)
    score -= min(due_cancellation_rate * 0.45, 25.0)

    if due_completion_rate < 80:
        score -= min(
            (80 - due_completion_rate) * 0.30,
            20.0,
        )

    health_score = int(
        round(max(0.0, min(score, 100.0)))
    )

    critical_overdue = (
        overdue_pending >= 10
        or (
            overdue_pending >= 5
            and overdue_rate >= 25
        )
        or (
            overdue_pending >= 3
            and overdue_rate >= 40
        )
    )
    critical_cancellation = (
        cancelled >= 5
        and due_cancellation_rate >= 25
    )
    critical_completion = (
        due_total >= 8
        and due_completion_rate < 50
        and overdue_pending > 0
    )

    if (
        critical_overdue
        or critical_cancellation
        or critical_completion
    ):
        if critical_overdue:
            reason = (
                f"يوجد {overdue_pending} موعد معلق تجاوز "
                f"تاريخه، بنسبة {overdue_rate}% من "
                "المواعيد المستحقة."
            )
            recommendation = (
                "راجع المواعيد المتأخرة وحدّثها إلى مكتملة "
                "أو ملغاة، واتصل بالمرضى عند الحاجة."
            )
        elif critical_cancellation:
            reason = (
                f"بلغت نسبة الإلغاء للمواعيد المستحقة "
                f"{due_cancellation_rate}%."
            )
            recommendation = (
                "راجع أسباب الإلغاء ومواعيد الأطباء وآلية "
                "التأكيد المسبق مع المرضى."
            )
        else:
            reason = (
                f"معدل إنجاز المواعيد المستحقة منخفض ويبلغ "
                f"{due_completion_rate}%."
            )
            recommendation = (
                "راجع سير العمل وتوزيع المواعيد وتحديث "
                "الحالات بعد انتهاء الزيارة."
            )

        return {
            "key": "critical",
            "label": "يحتاج تدخلاً",
            "score": health_score,
            "reason": reason,
            "recommendation": recommendation,
            "due_total": due_total,
            "due_completion_rate": due_completion_rate,
            "overdue_rate": overdue_rate,
        }

    warning_cancellation = (
        cancelled >= 2
        and due_cancellation_rate >= 12
    )
    warning_completion = (
        due_total >= 5
        and due_completion_rate < 70
    )

    if (
        overdue_pending > 0
        or warning_cancellation
        or warning_completion
    ):
        if overdue_pending > 0:
            reason = (
                f"يوجد {overdue_pending} موعد معلق تجاوز "
                "تاريخه ويحتاج إلى تحديث."
            )
            recommendation = (
                "تابع المواعيد المتأخرة قبل أن تتراكم."
            )
        elif warning_cancellation:
            reason = (
                f"نسبة الإلغاء الحالية "
                f"{due_cancellation_rate}% وتحتاج إلى متابعة."
            )
            recommendation = (
                "راقب أسباب الإلغاء وفعّل تأكيد الموعد."
            )
        else:
            reason = (
                f"معدل إنجاز المواعيد المستحقة "
                f"{due_completion_rate}%."
            )
            recommendation = (
                "تأكد من تحديث حالات المواعيد بعد كل زيارة."
            )

        return {
            "key": "warning",
            "label": "يحتاج متابعة",
            "score": health_score,
            "reason": reason,
            "recommendation": recommendation,
            "due_total": due_total,
            "due_completion_rate": due_completion_rate,
            "overdue_rate": overdue_rate,
        }

    return {
        "key": "healthy",
        "label": "الأداء جيد",
        "score": health_score,
        "reason": (
            "لا توجد مواعيد متأخرة أو مؤشرات تشغيلية خطرة."
        ),
        "recommendation": (
            "استمر على نمط العمل الحالي مع المتابعة الدورية."
        ),
        "due_total": due_total,
        "due_completion_rate": due_completion_rate,
        "overdue_rate": overdue_rate,
    }


def _build_smart_insights(
    *,
    summary: dict[str, Any],
    branches: list[dict[str, Any]],
    branch_scope_name: str | None = None,
) -> list[dict[str, str]]:
    """إنشاء تنبيهات مختصرة وقابلة للتنفيذ للمدير."""
    total = summary["total"]

    if total == 0:
        return [
            {
                "level": "info",
                "title": "لا توجد بيانات كافية",
                "message": (
                    "لا توجد مواعيد مسجلة خلال الفترة المختارة."
                ),
            }
        ]

    insights: list[dict[str, str]] = []

    overdue_pending = summary["overdue_pending"]
    cancellation_rate = summary["cancellation_rate"]
    completion_rate = summary["completion_rate"]
    health_key = summary["health_key"]

    active_branches = [
        branch
        for branch in branches
        if branch["total"] > 0
    ]

    if overdue_pending > 0:
        worst_overdue_branch = max(
            active_branches,
            key=lambda branch: branch["overdue_pending"],
            default=None,
        )

        branch_text = ""
        if (
            worst_overdue_branch
            and worst_overdue_branch["overdue_pending"] > 0
        ):
            branch_text = (
                f" وأكثرها في {worst_overdue_branch['name']} "
                f"بعدد "
                f"{worst_overdue_branch['overdue_pending']}."
            )

        insights.append(
            {
                "level": (
                    "danger"
                    if health_key == "critical"
                    else "warning"
                ),
                "title": "مواعيد متأخرة تحتاج إجراء",
                "message": (
                    f"يوجد {overdue_pending} موعد معلق "
                    f"تجاوز تاريخه.{branch_text}"
                ),
            }
        )

    if cancellation_rate >= 20:
        insights.append(
            {
                "level": "danger",
                "title": "ارتفاع في الإلغاءات",
                "message": (
                    f"وصلت نسبة الإلغاء إلى "
                    f"{cancellation_rate}%؛ راجع أسباب الإلغاء "
                    "وفعّل تأكيد المواعيد."
                ),
            }
        )

    if (
        completion_rate < 60
        and summary["due_total"] >= 5
        and overdue_pending == 0
    ):
        insights.append(
            {
                "level": "warning",
                "title": "معدل إنجاز منخفض",
                "message": (
                    f"معدل الإنجاز الحالي {completion_rate}%؛ "
                    "تحقق من تحديث حالات المواعيد بعد الزيارة."
                ),
            }
        )

    if active_branches and branch_scope_name is None:
        busiest_branch = max(
            active_branches,
            key=lambda branch: branch["total"],
        )

        insights.append(
            {
                "level": "positive",
                "title": "الفرع الأكثر نشاطًا",
                "message": (
                    f"{busiest_branch['name']} هو الأعلى نشاطًا "
                    f"بعدد {busiest_branch['total']} موعد."
                ),
            }
        )

        if len(active_branches) > 1:
            activity_share = _percentage(
                busiest_branch["total"],
                sum(
                    branch["total"]
                    for branch in active_branches
                ),
            )

            if activity_share >= 70:
                insights.append(
                    {
                        "level": "warning",
                        "title": "تركّز النشاط في فرع واحد",
                        "message": (
                            f"{activity_share}% من المواعيد تتركز "
                            f"في {busiest_branch['name']}؛ راجع "
                            "توزيع المرضى والكوادر بين الفروع."
                        ),
                    }
                )

    quiet_branches = [
        branch["name"]
        for branch in branches
        if branch["total"] == 0
    ]

    if quiet_branches:
        names = "، ".join(quiet_branches[:3])
        extra_count = len(quiet_branches) - 3

        if extra_count > 0:
            names = f"{names}، و{extra_count} فروع أخرى"

        insights.append(
            {
                "level": "info",
                "title": "فروع بدون نشاط",
                "message": (
                    f"لم تسجل الفروع التالية مواعيد خلال "
                    f"الفترة المختارة: {names}."
                ),
            }
        )

    has_risk_insight = any(
        insight["level"] in {
            "danger",
            "warning",
        }
        for insight in insights
    )

    if not has_risk_insight:
        insights.insert(
            0,
            {
                "level": "positive",
                "title": "الوضع التشغيلي مستقر",
                "message": (
                    "لم يتم اكتشاف مواعيد متأخرة أو مؤشرات "
                    "تشغيلية خطرة خلال الفترة المختارة."
                ),
            },
        )

    return insights[:5]


def build_dashboard_analytics(
    *,
    hospital: Any,
    days: int = 30,
    branch: Branch | None = None,
) -> dict[str, Any]:
    """
    إنشاء بيانات لوحة التحليلات المركزية.

    تُنفذ عمليات العد والجمع والتجميع داخل قاعدة البيانات،
    ولا تُحمّل سجلات المواعيد الكبيرة إلى ذاكرة التطبيق.
    """
    days = _normalise_days(days)

    end_date = timezone.localdate()
    start_date = end_date - timedelta(days=days - 1)

    branches_queryset = Branch.objects.filter(
        hospital=hospital,
        is_active=True,
    )

    if branch is not None:
        branches_queryset = branches_queryset.filter(
            pk=branch.pk,
        )

    branches = list(
        branches_queryset.order_by(
            "name",
            "pk",
        )
    )

    selected_scope_branch = (
        branches[0]
        if branch is not None and branches
        else None
    )

    branch_ids = [
        branch.pk
        for branch in branches
    ]

    appointments = Appointment.objects.filter(
        branch_id__in=branch_ids,
        scheduled_day__range=(
            start_date,
            end_date,
        ),
    )

    summary = appointments.aggregate(
        total=Count("pk"),
        completed=Count(
            "pk",
            filter=Q(
                status=AppointmentStatus.COMPLETED,
            ),
        ),
        pending=Count(
            "pk",
            filter=Q(
                status=AppointmentStatus.PENDING,
            ),
        ),
        cancelled=Count(
            "pk",
            filter=Q(
                status=AppointmentStatus.CANCELLED,
            ),
        ),
        overdue_pending=Count(
            "pk",
            filter=Q(
                status=AppointmentStatus.PENDING,
                scheduled_day__lt=end_date,
            ),
        ),
        today_pending=Count(
            "pk",
            filter=Q(
                status=AppointmentStatus.PENDING,
                scheduled_day=end_date,
            ),
        ),
        today_total=Count(
            "pk",
            filter=Q(
                scheduled_day=end_date,
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
        "completed",
        "pending",
        "cancelled",
        "overdue_pending",
        "today_pending",
        "today_total",
        "unique_patients",
    ):
        summary[key] = _as_int(summary.get(key))

    summary["revenue"] = _as_float(
        summary.get("revenue")
    )
    summary["resolved"] = (
        summary["completed"]
        + summary["cancelled"]
    )
    summary["pending_rate"] = _percentage(
        summary["pending"],
        summary["total"],
    )
    summary["completion_rate"] = _percentage(
        summary["completed"],
        summary["total"],
    )
    summary["cancellation_rate"] = _percentage(
        summary["cancelled"],
        summary["total"],
    )

    summary_health = _evaluate_branch_health(
        total=summary["total"],
        completed=summary["completed"],
        pending=summary["pending"],
        cancelled=summary["cancelled"],
        overdue_pending=summary["overdue_pending"],
        today_pending=summary["today_pending"],
    )

    summary["health_key"] = summary_health["key"]
    summary["health_label"] = summary_health["label"]
    summary["health_score"] = summary_health["score"]
    summary["health_reason"] = summary_health["reason"]
    summary["health_recommendation"] = (
        summary_health["recommendation"]
    )
    summary["due_total"] = summary_health["due_total"]
    summary["due_completion_rate"] = (
        summary_health["due_completion_rate"]
    )
    summary["overdue_rate"] = (
        summary_health["overdue_rate"]
    )

    daily_results = (
        appointments
        .values("scheduled_day")
        .annotate(
            total=Count("pk"),
            completed=Count(
                "pk",
                filter=Q(
                    status=AppointmentStatus.COMPLETED,
                ),
            ),
            pending=Count(
                "pk",
                filter=Q(
                    status=AppointmentStatus.PENDING,
                ),
            ),
            cancelled=Count(
                "pk",
                filter=Q(
                    status=AppointmentStatus.CANCELLED,
                ),
            ),
            revenue=Sum(
                "iqd_amount",
                filter=Q(
                    status=AppointmentStatus.COMPLETED,
                ),
            ),
        )
        .order_by("scheduled_day")
    )

    daily_map = {
        row["scheduled_day"]: row
        for row in daily_results
    }

    date_labels: list[str] = []
    total_trend: list[int] = []
    completed_trend: list[int] = []
    pending_trend: list[int] = []
    cancelled_trend: list[int] = []
    revenue_trend: list[float] = []

    current_date = start_date

    while current_date <= end_date:
        row = daily_map.get(current_date, {})

        date_labels.append(
            current_date.strftime("%d/%m")
        )
        total_trend.append(
            _as_int(row.get("total"))
        )
        completed_trend.append(
            _as_int(row.get("completed"))
        )
        pending_trend.append(
            _as_int(row.get("pending"))
        )
        cancelled_trend.append(
            _as_int(row.get("cancelled"))
        )
        revenue_trend.append(
            _as_float(row.get("revenue"))
        )

        current_date += timedelta(days=1)

    branch_results = (
        appointments
        .values("branch_id")
        .annotate(
            total=Count("pk"),
            completed=Count(
                "pk",
                filter=Q(
                    status=AppointmentStatus.COMPLETED,
                ),
            ),
            pending=Count(
                "pk",
                filter=Q(
                    status=AppointmentStatus.PENDING,
                ),
            ),
            cancelled=Count(
                "pk",
                filter=Q(
                    status=AppointmentStatus.CANCELLED,
                ),
            ),
            overdue_pending=Count(
                "pk",
                filter=Q(
                    status=AppointmentStatus.PENDING,
                    scheduled_day__lt=end_date,
                ),
            ),
            today_pending=Count(
                "pk",
                filter=Q(
                    status=AppointmentStatus.PENDING,
                    scheduled_day=end_date,
                ),
            ),
            revenue=Sum(
                "iqd_amount",
                filter=Q(
                    status=AppointmentStatus.COMPLETED,
                ),
            ),
        )
    )

    branch_result_map = {
        row["branch_id"]: row
        for row in branch_results
    }

    branch_data: list[dict[str, Any]] = []

    for branch in branches:
        result = branch_result_map.get(
            branch.pk,
            {},
        )

        total = _as_int(result.get("total"))
        completed = _as_int(result.get("completed"))
        pending = _as_int(result.get("pending"))
        cancelled = _as_int(result.get("cancelled"))
        overdue_pending = _as_int(
            result.get("overdue_pending")
        )
        today_pending = _as_int(
            result.get("today_pending")
        )

        health = _evaluate_branch_health(
            total=total,
            completed=completed,
            pending=pending,
            cancelled=cancelled,
            overdue_pending=overdue_pending,
            today_pending=today_pending,
        )

        branch_data.append(
            {
                "id": branch.pk,
                "name": branch.name,
                "code": branch.code,
                "total": total,
                "completed": completed,
                "pending": pending,
                "cancelled": cancelled,
                "overdue_pending": overdue_pending,
                "today_pending": today_pending,
                "revenue": _as_float(
                    result.get("revenue")
                ),
                "pending_rate": _percentage(
                    pending,
                    total,
                ),
                "completion_rate": _percentage(
                    completed,
                    total,
                ),
                "cancellation_rate": _percentage(
                    cancelled,
                    total,
                ),
                "due_total": health["due_total"],
                "due_completion_rate": (
                    health["due_completion_rate"]
                ),
                "overdue_rate": health["overdue_rate"],
                "health_key": health["key"],
                "health_label": health["label"],
                "health_score": health["score"],
                "health_reason": health["reason"],
                "health_recommendation": (
                    health["recommendation"]
                ),
            }
        )

    health_priority = {
        "critical": 0,
        "warning": 1,
        "healthy": 2,
        "quiet": 3,
    }

    branch_data.sort(
        key=lambda branch: (
            health_priority.get(
                branch["health_key"],
                9,
            ),
            -branch["total"],
            branch["name"],
        ),
    )

    insights = _build_smart_insights(
        summary=summary,
        branches=branch_data,
        branch_scope_name=(
            selected_scope_branch.name
            if selected_scope_branch
            else None
        ),
    )

    return {
        "scope": {
            "kind": (
                "branch"
                if selected_scope_branch
                else "hospital"
            ),
            "branch_id": (
                selected_scope_branch.pk
                if selected_scope_branch
                else None
            ),
            "branch_name": (
                selected_scope_branch.name
                if selected_scope_branch
                else None
            ),
        },
        "period": {
            "start": start_date,
            "end": end_date,
            "days": days,
        },
        "summary": summary,
        "branches": branch_data,
        "insights": insights,
        "charts": {
            "appointments": {
                "labels": date_labels,
                "total": total_trend,
                "completed": completed_trend,
                "pending": pending_trend,
                "cancelled": cancelled_trend,
            },
            "revenue": {
                "labels": date_labels,
                "values": revenue_trend,
            },
            "status": {
                "labels": [
                    "مكتملة",
                    "معلقة",
                    "ملغاة",
                ],
                "values": [
                    summary["completed"],
                    summary["pending"],
                    summary["cancelled"],
                ],
            },
            "branches": {
                "labels": [
                    branch["name"]
                    for branch in branch_data
                ],
                "total": [
                    branch["total"]
                    for branch in branch_data
                ],
                "completed": [
                    branch["completed"]
                    for branch in branch_data
                ],
                "pending": [
                    branch["pending"]
                    for branch in branch_data
                ],
                "cancelled": [
                    branch["cancelled"]
                    for branch in branch_data
                ],
                "overdue": [
                    branch["overdue_pending"]
                    for branch in branch_data
                ],
                "health_scores": [
                    (
                        branch["health_score"]
                        if branch["health_score"] is not None
                        else 0
                    )
                    for branch in branch_data
                ],
            },
        },
    }