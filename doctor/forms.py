# doctor/forms.py

from __future__ import annotations

from django import forms
from django.utils.translation import gettext_lazy as _

from .models import Doctor, validate_phone


class DoctorProfileForm(forms.ModelForm):
    """
    Doctor profile settings form.
    Only allows editing permitted fields.
    'full_name' and 'specialty' are read-only.
    """

    delete_photo = forms.BooleanField(
        required=False,
        label=_("Remove current photo"),
        widget=forms.CheckboxInput(attrs={"class": "form-check-input"}),
    )

    phone = forms.CharField(
        required=False,
        validators=[validate_phone],
        widget=forms.TextInput(
            attrs={
                "class": "form-control",
                "placeholder": "+9647XXXXXXXX",
                "inputmode": "tel",
                "pattern": r"^\+?\d{7,15}$",
                "autocomplete": "tel",
            }
        ),
        label=_("Phone Number"),
        help_text=_("Use international format, e.g. +9647XXXXXXXX."),
    )

    consultation_fee = forms.IntegerField(
        required=False,
        min_value=0,
        widget=forms.NumberInput(
            attrs={
                "class": "form-control",
                "placeholder": _("Consultation fee (IQD)"),
                "min": "0",
            }
        ),
        label=_("Consultation Fee"),
        help_text=_("Set 0 for free. Leave empty if not applicable."),
    )

    class Meta:
        model = Doctor
        fields = [
            "full_name",
            "specialty",
            "gender",
            "phone",
            "clinic_address",
            "photo",
            "short_bio",
            "available",
            "consultation_fee",
        ]
        widgets = {
            "full_name": forms.TextInput(
                attrs={"class": "form-control", "readonly": True, "tabindex": "-1"}
            ),
            "specialty": forms.TextInput(
                attrs={"class": "form-control", "readonly": True, "tabindex": "-1"}
            ),
            "gender": forms.Select(attrs={"class": "form-control"}),
            "clinic_address": forms.Textarea(
                attrs={
                    "class": "form-control",
                    "rows": 3,
                    "placeholder": _("Enter your clinic address here"),
                }
            ),
            "photo": forms.ClearableFileInput(attrs={"class": "form-control"}),
            "short_bio": forms.Textarea(
                attrs={
                    "class": "form-control",
                    "rows": 2,
                    "placeholder": _("Short description about you"),
                }
            ),
            "available": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }
        labels = {
            "full_name": _("Doctor Name"),
            "specialty": _("Specialization"),
            "gender": _("Gender"),
            "clinic_address": _("Clinic Address"),
            "photo": _("Profile Photo"),
            "short_bio": _("Short Bio"),
            "available": _("Available for Booking"),
            "consultation_fee": _("Consultation Fee"),
        }

    READONLY_FIELDS = ("full_name", "specialty")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Optional fields
        for fld in ("clinic_address", "photo", "short_bio", "phone", "consultation_fee"):
            if fld in self.fields:
                self.fields[fld].required = False

        # Strict read-only protection (UI + server-side)
        for fld in self.READONLY_FIELDS:
            if fld in self.fields:
                self.fields[fld].disabled = True

    # ----------------------------
    # Cleaning / Normalization
    # ----------------------------
    def clean_phone(self):
        """
        Normalize phone input:
        - empty -> None (better with null=True + unique constraint)
        - strip spaces
        """
        val = (self.cleaned_data.get("phone") or "").strip()
        if not val:
            return None
        # remove internal spaces
        val = "".join(val.split())
        return val

    def clean(self):
        cleaned = super().clean()

        # Enforce read-only fields values from instance (server-side)
        if self.instance and self.instance.pk:
            for fld in self.READONLY_FIELDS:
                cleaned[fld] = getattr(self.instance, fld)

        return cleaned

    # ----------------------------
    # Save
    # ----------------------------
    def save(self, commit: bool = True) -> Doctor:
        """
        Deletes current photo if requested, then saves.
        Calls Doctor.full_clean() to apply all model-level validations.
        """
        doc: Doctor = super().save(commit=False)

        # delete current photo physically
        if self.cleaned_data.get("delete_photo") and doc.photo:
            doc.photo.delete(save=False)
            doc.photo = None

        # Apply cleaned phone normalization to the model field
        # (important: empty string -> None)
        doc.phone = self.cleaned_data.get("phone", None)

        # Run model-level validation (includes phone normalization + theme validators + file checks)
        doc.full_clean()

        if commit:
            doc.save()
            self.save_m2m()

        return doc
