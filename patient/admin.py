"""
patient/admin.py
Refactor 06-Aug-2025 — Admin UX محسّن:
• شارات (badges) ملوّنة للحالات الثنائية وحالة السكري
• أعمدة أوضح (عُمر محسوب، تسمية التنبؤ)
• تصدير CSV احترافي بأعمدة مفهومة (labels) ودعم Excel/UTF-8
• تحسين الفلاتر والأداء عبر select_related
"""

from __future__ import annotations

import csv
import json
from typing import Sequence

from django.contrib import admin
from django.db.models import QuerySet
from django.http import HttpRequest, HttpResponse
from django.utils.html import format_html
from django.utils.translation import gettext_lazy as _, ngettext

from patient.models import DiabetesStatus, Patient


# ---------------------------------------------------------------------------- #
#                          أدوات العرض (Badges)                                #
# ---------------------------------------------------------------------------- #
def _yesno_badge(val: int | None) -> str:
    if val is None:
        return format_html('<span style="color:#6c757d;">—</span>')
    if int(val) == 1:
        return format_html('<span style="color:#0a7f39;font-weight:600;">{}</span>', _("Yes"))
    return format_html('<span style="color:#a00;font-weight:600;">{}</span>', _("No"))


def _status_badge(code: int | None) -> str:
    if code is None:
        return format_html('<span style="color:#6c757d;">{}</span>', _("Pending"))
    try:
        label = DiabetesStatus(code).label
    except Exception:
        label = _("Unknown")
    color_map = {0: "#0a7f39", 1: "#e69500", 2: "#a00"}
    color = color_map.get(int(code), "#6c757d")
    return format_html('<span style="color:{};font-weight:700;">{}</span>', color, label)


# ---------------------------------------------------------------------------- #
#                                ModelAdmin                                     #
# ---------------------------------------------------------------------------- #
@admin.register(Patient)
class PatientAdmin(admin.ModelAdmin):
    # --------------------------- الأعمدة في قائمة الجدول -------------------- #
    list_display: Sequence[str] = (
        "full_name",
        "age_col",
        "mobile",
        "email",
        "sex",
        "diabetes_status_col",
        "high_bp_col",
        "high_chol_col",
        "bmi",
        "hbA1c",
        "smoker_col",
        "doctor",
        "diabetes_prediction_label",
        "created_at",
    )
    list_display_links = ("full_name",)
    list_select_related = ("doctor", "doctor__user")
    ordering = ("-created_at",)
    list_per_page = 25

    # --------------------------- البحث والفلاتر ---------------------------- #
    search_fields = ("full_name", "mobile", "email")
    list_filter = (
        ("sex", admin.ChoicesFieldListFilter),
        ("diabetes_status", admin.ChoicesFieldListFilter),
        ("high_bp", admin.ChoicesFieldListFilter),
        ("high_chol", admin.ChoicesFieldListFilter),
        ("smoker", admin.ChoicesFieldListFilter),
        ("heart_disease_or_attack", admin.ChoicesFieldListFilter),
        ("phys_activity", admin.ChoicesFieldListFilter),
        ("gen_hlth", admin.ChoicesFieldListFilter),
        "doctor",
        ("created_at", admin.DateFieldListFilter),
    )
    date_hierarchy = "created_at"
    autocomplete_fields = ("doctor",)

    readonly_fields = ("display_age", "diabetes_prediction_label", "created_at")

    # ----------------------- مجموعات الحقول داخل التفاصيل ------------------- #
    fieldsets = (
        (_("Account Link"), {"fields": ("user",), "classes": ("collapse",)}),
        (
            _("Basic Info"),
            {"fields": ("full_name", "date_of_birth", "sex", "mobile", "email", "address")},
        ),
        (
            _("BRFSS Health Indicators"),
            {
                "fields": (
                    "diabetes_status",
                    "high_bp",
                    "high_chol",
                    "chol_check",
                    "bmi",
                    "hbA1c",
                    "smoker",
                    "stroke",
                    "heart_disease_or_attack",
                    "phys_activity",
                    "fruits",
                    "veggies",
                    "hvy_alcohol_consump",
                    "any_healthcare",
                    "no_doc_bc_cost",
                    "gen_hlth",
                    "ment_hlth",
                    "phys_hlth",
                    "diff_walk",
                    "education",
                    "income",
                )
            },
        ),
        (_("Medical Details"), {"fields": ("past_medical_history", "drug_history", "investigations")}),
        (_("Doctor & Notes"), {"fields": ("doctor", "clinical_notes")}),
        (_("Meta"), {"fields": ("display_age", "diabetes_prediction_label", "created_at"), "classes": ("collapse",)}),
    )

    # ---------------------------- أعمدة مخصّصة ----------------------------- #
    @admin.display(ordering="date_of_birth", description=_("Age"))
    def age_col(self, obj: Patient) -> str:
        return str(obj.display_age) if obj.display_age is not None else "—"

    @admin.display(description=_("Dx Status"))
    def diabetes_status_col(self, obj: Patient) -> str:
        return _status_badge(obj.diabetes_status)

    @admin.display(description=_("High BP"))
    def high_bp_col(self, obj: Patient) -> str:
        return _yesno_badge(obj.high_bp)

    @admin.display(description=_("High Chol"))
    def high_chol_col(self, obj: Patient) -> str:
        return _yesno_badge(obj.high_chol)

    @admin.display(description=_("Smoker"))
    def smoker_col(self, obj: Patient) -> str:
        return _yesno_badge(obj.smoker)

    @admin.display(description=_("AI Prediction"))
    def diabetes_prediction_label(self, obj: Patient) -> str:
        if obj.diabetes_prediction is None:
            return "—"
        try:
            return DiabetesStatus(obj.diabetes_prediction).label
        except Exception:
            return _("Unknown")

    # الأداء
    def get_queryset(self, request: HttpRequest) -> QuerySet[Patient]:
        qs = super().get_queryset(request).select_related("doctor", "doctor__user")
        return qs

    # ---------------------------- الإجراءات --------------------------------- #
    actions = ("export_as_csv", "recalculate_prediction")

    @admin.action(description=_("Export selected patients to CSV"))
    def export_as_csv(self, request: HttpRequest, queryset: QuerySet[Patient]) -> HttpResponse:
        """
        تصدير CSV بصيغة صديقة لبرنامج Excel، مع رؤوس واضحة وقيم labels للـchoices.
        """
        # رؤوس مخصّصة ومفهومة
        headers = [
            "id",
            "full_name",
            "date_of_birth",
            "age_years",
            "sex",
            "mobile",
            "email",
            "address",
            "doctor_id",
            "doctor_name",
            "diabetes_status",
            "diabetes_prediction",
            "prediction_proba",
            "bmi",
            "hbA1c",
            "high_bp",
            "high_chol",
            "chol_check",
            "smoker",
            "stroke",
            "heart_disease_or_attack",
            "phys_activity",
            "fruits",
            "veggies",
            "hvy_alcohol_consump",
            "any_healthcare",
            "no_doc_bc_cost",
            "gen_hlth",
            "ment_hlth",
            "phys_hlth",
            "diff_walk",
            "education",
            "income",
            "created_at",
        ]

        # UTF-8 مع BOM حتى يفتح بشكل صحيح في Excel
        response = HttpResponse(content_type="text/csv; charset=utf-8")
        response["Content-Disposition"] = "attachment; filename=patients.csv"
        response.write("\ufeff")  # BOM

        writer = csv.writer(response, lineterminator="\n", quoting=csv.QUOTE_MINIMAL)
        writer.writerow(headers)

        for obj in queryset:
            # قيم labels للحقول الفئوية
            sex = obj.get_sex_display() if obj.sex else ""
            dx_status = obj.get_diabetes_status_display() if obj.diabetes_status is not None else ""
            dx_pred = obj.get_diabetes_status_display() if False else ""  # placeholder
            if obj.diabetes_prediction is not None:
                try:
                    dx_pred = DiabetesStatus(obj.diabetes_prediction).label
                except Exception:
                    dx_pred = "?"

            gen_hlth = obj.get_gen_hlth_display() if obj.gen_hlth is not None else ""
            education = obj.get_education_display() if obj.education is not None else ""
            income = obj.get_income_display() if obj.income is not None else ""

            # ثنائيات 0/1 كنصوص Yes/No
            def yf(v: int | None) -> str:
                if v is None:
                    return ""
                return _("Yes") if int(v) == 1 else _("No")

            row = [
                obj.pk,
                obj.full_name,
                obj.date_of_birth.isoformat() if obj.date_of_birth else "",
                obj.display_age if obj.display_age is not None else "",
                sex,
                obj.mobile or "",
                obj.email or "",
                obj.address or "",
                obj.doctor_id or "",
                (obj.doctor.user.get_full_name() if obj.doctor and obj.doctor.user else getattr(obj.doctor, "full_name", "")) or "",
                dx_status,
                dx_pred,
                json.dumps(obj.prediction_proba, ensure_ascii=False) if obj.prediction_proba else "",
                obj.bmi if obj.bmi is not None else "",
                obj.hbA1c if obj.hbA1c is not None else "",
                yf(obj.high_bp),
                yf(obj.high_chol),
                yf(obj.chol_check),
                yf(obj.smoker),
                yf(obj.stroke),
                yf(obj.heart_disease_or_attack),
                yf(obj.phys_activity),
                yf(obj.fruits),
                yf(obj.veggies),
                yf(obj.hvy_alcohol_consump),
                yf(obj.any_healthcare),
                yf(obj.no_doc_bc_cost),
                gen_hlth,
                obj.ment_hlth if obj.ment_hlth is not None else "",
                obj.phys_hlth if obj.phys_hlth is not None else "",
                yf(obj.diff_walk),
                education,
                income,
                obj.created_at.isoformat() if obj.created_at else "",
            ]
            writer.writerow(row)

        return response

    @admin.action(description=_("Recalculate diabetes prediction via AI"))
    def recalculate_prediction(self, request: HttpRequest, queryset: QuerySet[Patient]) -> None:
        """
        يعيد حساب التنبؤ باستخدام خدمة ML. يتجاوز الأخطاء ويبلغ العدد الناجح.
        """
        try:
            from patient.services import predict_and_save  # استيراد متأخر لتخفيف التحميل
        except Exception as ex:  # pragma: no cover
            self.message_user(request, _("Prediction service unavailable: %s") % ex, level="error")
            return

        changed = 0
        errors = 0
        for p in queryset:
            old = p.diabetes_prediction
            try:
                predict_and_save(p)  # يفترض أن يقوم بالحفظ داخليًا
                if p.diabetes_prediction != old:
                    changed += 1
            except Exception:
                errors += 1
                continue

        msg = ngettext(
            "%d patient updated with new prediction.",
            "%d patients updated with new prediction.",
            changed,
        ) % changed
        if errors:
            msg += " " + ngettext(
                "(%d error skipped.)",
                "(%d errors skipped.)",
                errors,
            ) % errors
        self.message_user(request, msg)
