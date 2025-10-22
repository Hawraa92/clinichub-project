# doctor/forms.py

from django import forms
from django.utils.translation import gettext_lazy as _

from .models import Doctor, phone_validator


class DoctorProfileForm(forms.ModelForm):
    """
    نموذج يتيح للطبيب تعديل بياناته المسموح بها فقط.
    الحقول 'full_name' و 'specialty' للقراءة ولا يمكن تعديلها.
    """

    delete_photo = forms.BooleanField(
        required=False,
        label=_("Remove current photo"),
        widget=forms.CheckboxInput(attrs={"class": "form-check-input"}),
    )

    phone = forms.CharField(
        required=False,
        validators=[phone_validator],
        widget=forms.TextInput(
            attrs={
                "class": "form-control",
                "placeholder": "+9647XXXXXXXX",
                "inputmode": "tel",
                "pattern": r"^\+?\d{7,15}$",
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
            }
        ),
        label=_("Consultation Fee"),
        help_text=_("Leave empty if not applicable."),
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
        }

    READONLY_FIELDS = ("full_name", "specialty")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        for fld in ("clinic_address", "photo", "short_bio"):
            self.fields[fld].required = False

        for fld in self.READONLY_FIELDS:
            self.fields[fld].disabled = True

    def clean(self):
        cleaned = super().clean()
        if self.instance and self.instance.pk:
            for fld in self.READONLY_FIELDS:
                cleaned[fld] = getattr(self.instance, fld)
        return cleaned

    def save(self, commit: bool = True) -> Doctor:
        """
        حذف الصورة فعليًا عند اختيار 'delete_photo' ثم حفظ التعديلات.
        يُستدعى full_clean() لتطبيق كل قواعد التحقق في نموذج Doctor.
        """
        doc: Doctor = super().save(commit=False)

        if self.cleaned_data.get("delete_photo") and doc.photo:
            doc.photo.delete(save=False)
            doc.photo = None

        doc.full_clean()

        if commit:
            doc.save()
            self.save_m2m()
        return doc
