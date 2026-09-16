"""
patient/admin.py
Refactor 04-Feb-2026 — Admin UX محسّن + تصدير CSV أدق + إعادة حساب تنبؤ أكثر موثوقية:

✅ Badges ملوّنة للحالات الثنائية وحالة السكري والتنبؤ
✅ أعمدة أوضح (عمر محسوب، تسمية التشخيص، تسمية التنبؤ)
✅ CSV احترافي صديق Excel (UTF-8 BOM) + أعمدة (code + label) للـchoices
✅ تحسين الأداء: select_related + قيم آمنة + helpers مركّزة
✅ Action لإعادة حساب التنبؤ مع refresh_from_db وعدّاد changed صحيح ورسائل Django messages الصحيحة
"""

from __future__ import annotations

import csv
import json
from typing import Sequence

from django.contrib import admin, messages
from django.db.models import QuerySet
from django.http import HttpRequest, HttpResponse
from django.utils.html import format_html
from django.utils.translation import gettext_lazy as _, ngettext

from patient.models import DiabetesStatus, Patient


# ---------------------------------------------------------------------------- #
#                               Helpers / Badges                               #
# ---------------------------------------------------------------------------- #
def _dash() -> str:
    return format_html('<span style="color:#6c757d;">—</span>')


def _yesno_badge(val: int | None) -> str:
    """
    1 => Yes (green) | 0 => No (red) | None => —
    """
    if val is None:
        return _dash()
    if int(val) == 1:
        return format_html('<span style="color:#0a7f39;font-weight:700;">{}</span>', _("Yes"))
    return format_html('<span style="color:#a00;font-weight:700;">{}</span>', _("No"))


def _diabetes_status_badge(code: int | None) -> str:
    """
    DiabetesStatus:
      0 => (green) | 1 => (orange) | 2 => (red)
    """
    if code is None:
        return format_html('<span style="color:#6c757d;font-weight:600;">{}</span>', _("Pending"))
    try:
        label = DiabetesStatus(int(code)).label
    except Exception:
        label = _("Unknown")

    color_map = {0: "#0a7f39", 1: "#e69500", 2: "#a00"}
    color = color_map.get(int(code), "#6c757d")
    return format_html('<span style="color:{};font-weight:800;">{}</span>', color, label)


def _safe_label(enum_cls, code: int | None, unknown: str = "?") -> str:
    if code is None:
        return ""
    try:
        return enum_cls(int(code)).label
    except Exception:
        return unknown


def _safe_choice_display(obj: Patient, field: str) -> str:
    """
    يرجع get_FIELD_display بشكل آمن (بدون كسر إذا الحقل أو الدالة مو موجودة).
    """
    try:
        fn = getattr(obj, f"get_{field}_display", None)
        if callable(fn):
            return fn() or ""
    except Exception:
        pass
    return ""


def _yn_text(val: int | None) -> str:
    """
    CSV: 1 => Yes | 0 => No | None => ""
    """
    if val is None:
        return ""
    return _("Yes") if int(val) == 1 else _("No")


def _doctor_name(obj: Patient) -> str:
    """
    اسم الطبيب بشكل آمن (Doctor.user.get_full_name أو fallback).
    """
    try:
        if obj.doctor and getattr(obj.doctor, "user", None):
            return obj.doctor.user.get_full_name() or obj.doctor.user.username or ""
    except Exception:
        pass
    return getattr(obj.doctor, "full_name", "") or ""


# ---------------------------------------------------------------------------- #
#                                  ModelAdmin                                  #
# ---------------------------------------------------------------------------- #
@admin.register(Patient)
class PatientAdmin(admin.ModelAdmin):
    # --------------------------- Columns in changelist ---------------------- #
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

    # --------------------------- Search & filters --------------------------- #
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

    # ----------------------- Field groups in detail form -------------------- #
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

    # ---------------------------- Custom columns ---------------------------- #
    @admin.display(ordering="date_of_birth", description=_("Age"))
    def age_col(self, obj: Patient) -> str:
        return str(obj.display_age) if obj.display_age is not None else "—"

    @admin.display(description=_("Dx Status"))
    def diabetes_status_col(self, obj: Patient) -> str:
        return _diabetes_status_badge(obj.diabetes_status)

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
        """
        عرض label للتنبؤ المخزّن (diabetes_prediction).
        """
        if obj.diabetes_prediction is None:
            return "—"
        try:
            return DiabetesStatus(int(obj.diabetes_prediction)).label
        except Exception:
            return _("Unknown")

    # ---------------------------- Performance -------------------------------- #
    def get_queryset(self, request: HttpRequest) -> QuerySet[Patient]:
        # select_related هنا + list_select_related بالأعلى = ok (double is harmless)
        return super().get_queryset(request).select_related("doctor", "doctor__user")

    # ---------------------------- Actions ------------------------------------ #
    actions = ("export_as_csv", "recalculate_prediction")

    @admin.action(description=_("Export selected patients to CSV"))
    def export_as_csv(self, request: HttpRequest, queryset: QuerySet[Patient]) -> HttpResponse:
        """
        تصدير CSV بصيغة صديقة لبرنامج Excel، مع رؤوس واضحة.
        ✅ يضيف code + label للحقول الفئوية المهمة (diabetes_status / diabetes_prediction)
        ✅ BOM لفتح صحيح في Excel
        """
        headers = [
            "id",
            "full_name",
            "date_of_birth",
            "age_years",
            "sex_label",
            "mobile",
            "email",
            "address",
            "doctor_id",
            "doctor_name",
            "diabetes_status_code",
            "diabetes_status_label",
            "diabetes_prediction_code",
            "diabetes_prediction_label",
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
            "gen_hlth_label",
            "ment_hlth",
            "phys_hlth",
            "diff_walk",
            "education_label",
            "income_label",
            "created_at",
        ]

        response = HttpResponse(content_type="text/csv; charset=utf-8")
        response["Content-Disposition"] = "attachment; filename=patients.csv"
        response.write("\ufeff")  # UTF-8 BOM for Excel

        writer = csv.writer(response, lineterminator="\n", quoting=csv.QUOTE_MINIMAL)
        writer.writerow(headers)

        for obj in queryset:
            sex_label = _safe_choice_display(obj, "sex")
            gen_hlth_label = _safe_choice_display(obj, "gen_hlth")
            education_label = _safe_choice_display(obj, "education")
            income_label = _safe_choice_display(obj, "income")

            dx_status_code = obj.diabetes_status
            dx_status_label = _safe_label(DiabetesStatus, obj.diabetes_status, unknown="?")

            pred_code = obj.diabetes_prediction
            pred_label = _safe_label(DiabetesStatus, obj.diabetes_prediction, unknown="?")

            proba = ""
            if obj.prediction_proba:
                try:
                    proba = json.dumps(obj.prediction_proba, ensure_ascii=False)
                except Exception:
                    proba = ""

            row = [
                obj.pk,
                obj.full_name or "",
                obj.date_of_birth.isoformat() if obj.date_of_birth else "",
                obj.display_age if obj.display_age is not None else "",
                sex_label,
                obj.mobile or "",
                obj.email or "",
                obj.address or "",
                obj.doctor_id or "",
                _doctor_name(obj),
                dx_status_code if dx_status_code is not None else "",
                dx_status_label,
                pred_code if pred_code is not None else "",
                pred_label,
                proba,
                obj.bmi if obj.bmi is not None else "",
                obj.hbA1c if obj.hbA1c is not None else "",
                _yn_text(obj.high_bp),
                _yn_text(obj.high_chol),
                _yn_text(obj.chol_check),
                _yn_text(obj.smoker),
                _yn_text(obj.stroke),
                _yn_text(obj.heart_disease_or_attack),
                _yn_text(obj.phys_activity),
                _yn_text(obj.fruits),
                _yn_text(obj.veggies),
                _yn_text(obj.hvy_alcohol_consump),
                _yn_text(obj.any_healthcare),
                _yn_text(obj.no_doc_bc_cost),
                gen_hlth_label,
                obj.ment_hlth if obj.ment_hlth is not None else "",
                obj.phys_hlth if obj.phys_hlth is not None else "",
                _yn_text(obj.diff_walk),
                education_label,
                income_label,
                obj.created_at.isoformat() if obj.created_at else "",
            ]
            writer.writerow(row)

        return response

    @admin.action(description=_("Recalculate diabetes prediction via AI"))
    def recalculate_prediction(self, request: HttpRequest, queryset: QuerySet[Patient]) -> None:
        """
        يعيد حساب التنبؤ باستخدام خدمة ML:
        - يتجاوز الأخطاء
        - يعدّ changed بشكل صحيح عبر refresh_from_db
        """
        try:
            from patient.services import predict_and_save  # lazy import
        except Exception as ex:  # pragma: no cover
            self.message_user(
                request,
                _("Prediction service unavailable: %s") % ex,
                level=messages.ERROR,
            )
            return

        changed = 0
        errors = 0

        for p in queryset:
            old = p.diabetes_prediction
            try:
                predict_and_save(p)  # يفترض الحفظ داخليًا (أو يغيّر ثم يحفظ)
                # لضمان قراءة النتيجة الفعلية من DB (حتى لو الدالة تحفظ بدون تحديث instance)
                p.refresh_from_db(fields=["diabetes_prediction"])
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

        self.message_user(request, msg, level=messages.INFO)
