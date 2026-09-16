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

try:
    import phonenumbers as _pn  # type: ignore
    _HAS_PN = True
except Exception:
    _HAS_PN = False


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
            parsed = _pn.parse(normalized, "IQ")
            normalized = _pn.format_number(parsed, _pn.PhoneNumberFormat.E164)
        except Exception:
            pass
    return normalized


class DoctorQuerysetMixin:
    def _available_doctors_qs(self):
        qs = Doctor.objects.select_related("user").all()

        if hasattr(Doctor, "available"):
            qs = qs.filter(available=True)
        elif hasattr(Doctor, "is_available"):
            qs = qs.filter(is_available=True)

        try:
            Doctor._meta.get_field("full_name")  # type: ignore[attr-defined]
            qs = qs.order_by(Lower("full_name"))
        except Exception:
            qs = qs.order_by(Lower("user__first_name"), Lower("user__last_name"))

        return qs

    def _setup_doctor_field(self) -> None:
        if "doctor" not in self.fields:
            return

        f: forms.ModelChoiceField = self.fields["doctor"]  # type: ignore[assignment]
        f.queryset = self._available_doctors_qs()
        f.empty_label = _("— Select a doctor —")

        def _label(obj: Doctor) -> str:
            name = getattr(obj, "full_name", "") or ""
            if name:
                return str(name)
            u = getattr(obj, "user", None)
            if u:
                return u.get_full_name() or getattr(u, "username", "") or str(obj)
            return str(obj)

        f.label_from_instance = _label  # type: ignore[assignment]

        css = f.widget.attrs.get("class", "")
        f.widget.attrs["class"] = (css + " form-select").strip()


class BasePatientForm(forms.ModelForm, DoctorQuerysetMixin):
    class Meta:
        model = Patient
        fields: tuple[str, ...] = ()

        widgets = {
            "full_name": forms.TextInput(
                attrs={"placeholder": _("Full name"), "class": "form-control"}
            ),
            "date_of_birth": forms.DateInput(
                attrs={"type": "date", "class": "form-control"}
            ),
            "sex": forms.Select(attrs={"class": "form-select"}),
            "nationality": forms.TextInput(
                attrs={"placeholder": _("Nationality"), "class": "form-control"}
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
            "bmi": forms.NumberInput(
                attrs={"step": "0.1", "min": "10", "max": "80", "class": "form-control"}
            ),
            "hbA1c": forms.NumberInput(
                attrs={"step": "0.1", "min": "3", "max": "15", "class": "form-control"}
            ),
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
            "doctor": forms.Select(attrs={"class": "form-select"}),
        }

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self.locked_doctor = kwargs.pop("locked_doctor", None)
        super().__init__(*args, **kwargs)

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
            if fname in self.fields and fname != "sex":
                choices = enum_cls if isinstance(enum_cls, list) else enum_cls.choices
                self.fields[fname].widget = forms.Select(
                    choices=choices,
                    attrs={"class": "form-select"},
                )

        for fname in ("ment_hlth", "phys_hlth"):
            if fname in self.fields:
                self.fields[fname].widget.attrs.update(
                    {"type": "number", "min": "0", "max": "30"}
                )

        self._setup_doctor_field()

        if "doctor" in self.fields and self.locked_doctor is not None:
            try:
                self.fields["doctor"].queryset = Doctor.objects.filter(pk=self.locked_doctor.pk)
                self.initial["doctor"] = self.locked_doctor
                self.fields["doctor"].disabled = True
            except Exception:
                pass

        if "doctor" in self.fields:
            self.fields["doctor"].error_messages.setdefault(
                "required", _("Please select a doctor.")
            )

    def clean_full_name(self) -> str:
        value: str = self.cleaned_data.get("full_name", "")
        value = _collapse_ws(value) or ""
        if not value:
            raise ValidationError(_("Full name is required."))
        return value

    def clean_nationality(self) -> Optional[str]:
        val = self.cleaned_data.get("nationality")
        val = _collapse_ws(val)
        return val or None

    def clean_email(self) -> Optional[str]:
        email = _normalize_email(self.cleaned_data.get("email"))
        if not email:
            return email

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
        qs = Patient.objects.filter(mobile=normalized)
        if self.instance and self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise ValidationError(_("This mobile number is already used by another patient."))
        return normalized

    def clean(self) -> dict[str, Any]:
        data = super().clean()

        hb = data.get("hbA1c")
        if hb is not None and (hb < 3 or hb > 15):
            self.add_error("hbA1c", _("HbA1c must be between 3.0 and 15.0."))

        bmi = data.get("bmi")
        if bmi is not None and (bmi < 10 or bmi > 80):
            self.add_error("bmi", _("BMI must be between 10.0 and 80.0."))

        return data


class DoctorPatientForm(BasePatientForm):
    class Meta(BasePatientForm.Meta):
        fields = [
            "full_name",
            "date_of_birth",
            "sex",
            "nationality",
            "mobile",
            "email",
            "address",
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
            "diabetes_status",
            "past_medical_history",
            "drug_history",
            "investigations",
            "clinical_notes",
        ]


class SecretaryPatientForm(BasePatientForm):
    class Meta(BasePatientForm.Meta):
        fields = [
            "full_name",
            "date_of_birth",
            "sex",
            "nationality",
            "mobile",
            "email",
            "address",
        ]
