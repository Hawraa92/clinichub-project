"""
patient/forms.py
Refactor 06-Aug-2025 — متوافق مع نموذج Patient الجديد، تنظيف ذكي، تفريد مُسبق
"""

from __future__ import annotations

from typing import Any, Optional

from django import forms
from django.core.exceptions import ValidationError
from django.db.models.functions import Lower
from django.utils.translation import gettext_lazy as _

from doctor.models import Doctor
from patient.models import (
    Patient,
    YesNo,
    Sex,
    GeneralHealth,
    EducationLevel,
    IncomeLevel,
)

# --------------------------------------------------------------- #
#           Optional: phonenumbers for strict parsing             #
# --------------------------------------------------------------- #
try:
    import phonenumbers as _pn  # type: ignore
    _HAS_PN = True
except Exception:  # pragma: no cover
    _HAS_PN = False


# --------------------------------------------------------------- #
#                Utilities for normalization                      #
# --------------------------------------------------------------- #
def _collapse_ws(text: Optional[str]) -> Optional[str]:
    if not text:
        return text
    return " ".join(text.split()).strip()


def _normalize_email(email: Optional[str]) -> Optional[str]:
    if not email:
        return email
    return email.strip().lower()


def _normalize_mobile(mobile: Optional[str]) -> Optional[str]:
    if not mobile:
        return mobile
    normalized = mobile.strip().replace(" ", "")
    if _HAS_PN:
        try:
            parsed = _pn.parse(normalized, "IQ")  # default region: Iraq
            normalized = _pn.format_number(parsed, _pn.PhoneNumberFormat.E164)
        except Exception:
            # keep raw; model validators will still run
            pass
    return normalized


# --------------------------------------------------------------- #
#                Mixin: تجهيز قائمة الأطباء                       #
# --------------------------------------------------------------- #
class DoctorQuerysetMixin:
    """يملأ حقل doctor بقائمة الأطباء المتاحين فقط، مرتَّبة بالاسم."""

    def _setup_doctor_field(self) -> None:
        if "doctor" not in self.fields:
            return
        qs = (
            Doctor.objects.filter(available=True)
            .select_related("user")
            .order_by(Lower("full_name"))
        )
        f: forms.ModelChoiceField = self.fields["doctor"]  # type: ignore[assignment]
        f.queryset = qs
        f.empty_label = _("— Select a doctor —")
        f.label_from_instance = (
            lambda obj: obj.full_name or obj.user.get_full_name() or str(obj)
        )
        css = f.widget.attrs.get("class", "")
        f.widget.attrs["class"] = (css + " form-select").strip()


# --------------------------------------------------------------- #
#             Base: كل نماذج المرضى ترث منه                       #
# --------------------------------------------------------------- #
class BasePatientForm(forms.ModelForm, DoctorQuerysetMixin):
    """قالب مشترك يحوي الـ widgets وأسلوب Bootstrap والتنظيف العام."""

    class Meta:
        model = Patient
        fields: tuple[str, ...] = ()  # يُحدَّد في النماذج المشتقة

        widgets = {
            # هوية المريض
            "full_name": forms.TextInput(
                attrs={"placeholder": _("Full name"), "class": "form-control"}
            ),
            "date_of_birth": forms.DateInput(
                attrs={"type": "date", "class": "form-control"}
            ),
            "mobile": forms.TextInput(
                attrs={
                    "type": "tel",
                    "inputmode": "tel",
                    "pattern": r"^\+?\d{7,15}$",
                    "placeholder": _("e.g. +9647701234567"),
                    "class": "form-control",
                }
            ),
            "email": forms.EmailInput(
                attrs={"placeholder": _("name@example.com"), "class": "form-control"}
            ),
            "address": forms.TextInput(
                attrs={"placeholder": _("Address"), "class": "form-control"}
            ),
            # قيَم مخبريّة / قياسات
            "bmi": forms.NumberInput(
                attrs={"step": "0.1", "min": "10", "max": "80", "class": "form-control"}
            ),
            "hbA1c": forms.NumberInput(
                attrs={"step": "0.1", "min": "3", "max": "15", "class": "form-control"}
            ),
            # حقول نصية طويلة
            "past_medical_history": forms.Textarea(
                attrs={"rows": 3, "class": "form-control"}
            ),
            "drug_history": forms.Textarea(
                attrs={"rows": 3, "class": "form-control"}
            ),
            "investigations": forms.Textarea(
                attrs={"rows": 3, "class": "form-control"}
            ),
            "clinical_notes": forms.Textarea(
                attrs={"rows": 3, "class": "form-control"}
            ),
            # اختيار الطبيب
            "doctor": forms.Select(attrs={"class": "form-select"}),
        }

    # ---------------------- init enhancements --------------------- #
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)

        # ضبط Widgets للحقول الفئوية/الثنائية
        choice_map = {
            "high_bp": YesNo,
            "high_chol": YesNo,
            "chol_check": YesNo,
            "smoker": YesNo,
            "stroke": YesNo,
            "heart_disease_or_attack": YesNo,
            "phys_activity": YesNo,
            "fruits": YesNo,
            "veggies": YesNo,
            "hvy_alcohol_consump": YesNo,
            "any_healthcare": YesNo,
            "no_doc_bc_cost": YesNo,
            "diff_walk": YesNo,
            "sex": Sex,
            "gen_hlth": GeneralHealth,
            "education": EducationLevel,
            "income": IncomeLevel,
            "diabetes_status": Patient._meta.get_field("diabetes_status").choices,
        }
        for fname, enum_cls in choice_map.items():
            if fname in self.fields:
                choices = enum_cls if isinstance(enum_cls, list) else enum_cls.choices
                self.fields[fname].widget = forms.Select(
                    choices=choices,
                    attrs={"class": "form-select"},
                )

        # حقول رقمية 0-30
        for fname in ("ment_hlth", "phys_hlth"):
            if fname in self.fields:
                self.fields[fname].widget.attrs.update(
                    {"type": "number", "min": "0", "max": "30"}
                )

        # تجهيز قائمة الأطباء
        self._setup_doctor_field()

        # رسائل خطأ ودودة
        if "doctor" in self.fields:
            self.fields["doctor"].error_messages.setdefault("required", _("Please select a doctor."))

    # ---------------------- field cleaners ------------------------ #
    def clean_full_name(self) -> str:
        value: str = self.cleaned_data.get("full_name", "")
        value = _collapse_ws(value) or ""
        if not value:
            raise ValidationError(_("Full name is required."))
        return value

    def clean_email(self) -> Optional[str]:
        email = _normalize_email(self.cleaned_data.get("email"))
        if not email:
            return email
        # تفريد الإيميل (غير حساس لحالة الأحرف)
        qs = Patient.objects.filter(email__iexact=email)
        if self.instance and self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise ValidationError(_("This email is already used by another patient."))
        return email

    def clean_mobile(self) -> Optional[str]:
        mobile = self.cleaned_data.get("mobile")
        if not mobile:
            return mobile
        normalized = _normalize_mobile(mobile)
        # تفريد الموبايل بعد التطبيع
        qs = Patient.objects.filter(mobile=normalized)
        if self.instance and self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise ValidationError(_("This mobile number is already used by another patient."))
        return normalized

    # -------------------- cross-field cleaner --------------------- #
    def clean(self) -> dict[str, Any]:
        data = super().clean()

        # رسائل أوضح للقيم خارج المدى
        hb = data.get("hbA1c")
        if hb is not None and (hb < 3 or hb > 15):
            self.add_error("hbA1c", _("HbA1c must be between 3.0 and 15.0."))

        bmi = data.get("bmi")
        if bmi is not None and (bmi < 10 or bmi > 80):
            self.add_error("bmi", _("BMI must be between 10.0 and 80.0."))

        return data


# --------------------------------------------------------------- #
#           نموذج الطبيب: إدخال/تعديل شامل                        #
# --------------------------------------------------------------- #
class DoctorPatientForm(BasePatientForm):
    """
    يُستخدم من قِبل الطبيب لإدخال/تعديل الحقول السريرية.
    ملاحظة: age_group يُحسَب تلقائياً (غير معروض).
    """

    class Meta(BasePatientForm.Meta):
        fields = [
            # هوية + تواصل
            "full_name",
            "date_of_birth",
            "sex",
            "mobile",
            "email",
            "address",
            # المتغيرات الطبية (BRFSS)
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
            # اختيار الطبيب
            "doctor",
            # الحالة التشخيصية اليدوية (اختياري)
            "diabetes_status",
            # ملاحظات إضافية
            "past_medical_history",
            "drug_history",
            "investigations",
            "clinical_notes",
        ]

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.fields["doctor"].required = True


# --------------------------------------------------------------- #
#          نموذج السكرتير: إدخال سريع ومبسّط                       #
# --------------------------------------------------------------- #
class SecretaryPatientForm(BasePatientForm):
    """نموذج مبسّط لإضافة مريض بسرعة من قِبل السكرتير."""

    class Meta(BasePatientForm.Meta):
        fields = [
            "full_name",
            "date_of_birth",
            "sex",
            "mobile",
            "email",
            "address",
            "doctor",
        ]

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.fields["doctor"].required = True
