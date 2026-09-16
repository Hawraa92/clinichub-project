# File: prescription/forms.py
import logging

from django import forms
from django.core.exceptions import ValidationError
from django.forms import inlineformset_factory

from appointments.models import Appointment
from .access import (
    admin_tenant_q,
    appointment_in_admin_scope,
    appointment_in_secretary_scope,
    secretary_can_access_prescriptions,
    secretary_tenant_q,
)
from .models import Medication, Prescription

logger = logging.getLogger(__name__)


class PrescriptionForm(forms.ModelForm):
    """
    Smart form for creating prescriptions.
    - Doctor/patient details are derived from the appointment.
    - Adds an archive option (form-only field).
    - Enforces RBAC on appointment selection.
    - Prevents duplicate prescriptions per appointment.
    - Supports Dx field (diagnosis).
    """

    # Form-only field (not in model)
    archive_prescription = forms.BooleanField(
        required=False,
        label="Save to Archive",
        help_text="Automatically archive this prescription for future reference.",
    )

    class Meta:
        model = Prescription
        fields = [
            "appointment",
            "patient_full_name",
            "age",
            "diagnosis",          # ✅ Dx
            "instructions",
            "voice_note",
            "doctor_signature",
            "doctor_logo",
        ]
        widgets = {
            "appointment": forms.Select(attrs={"class": "form-select"}),

            "patient_full_name": forms.TextInput(
                attrs={"class": "form-control bg-light"}
            ),
            "age": forms.NumberInput(
                attrs={"class": "form-control bg-light"}
            ),

            # ✅ Dx (CharField بالموديل، الأفضل TextInput)
            "diagnosis": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "Dx / Diagnosis… (مثال: Acute pharyngitis / GERD / PCOS)",
                }
            ),

            "instructions": forms.Textarea(
                attrs={
                    "class": "form-control",
                    "rows": 3,
                    "placeholder": "Additional instructions…",
                }
            ),
            "voice_note": forms.ClearableFileInput(attrs={"class": "form-control"}),
            "doctor_signature": forms.ClearableFileInput(attrs={"class": "form-control"}),
            "doctor_logo": forms.ClearableFileInput(attrs={"class": "form-control"}),
        }

    def __init__(self, *args, **kwargs):
        appointment_id = kwargs.pop("appointment_id", None)
        self.user = kwargs.pop("user", None)  # ✅ RBAC
        super().__init__(*args, **kwargs)

        # checkbox styling
        self.fields["archive_prescription"].widget.attrs.update(
            {"class": "form-check-input"}
        )

        # patient name + age are derived from appointment (display only)
        self.fields["patient_full_name"].required = False
        self.fields["age"].required = False
        self.fields["patient_full_name"].disabled = True
        self.fields["age"].disabled = True

        # Dx optional
        if "diagnosis" in self.fields:
            self.fields["diagnosis"].required = False

        # ✅ Restrict appointment queryset by role
        if "appointment" in self.fields:
            qs = Appointment.objects.select_related("patient", "doctor", "doctor__user")

            if self.user and not getattr(self.user, "is_superuser", False):
                role = getattr(self.user, "role", None)

                if role == "doctor":
                    qs = qs.filter(doctor__user=self.user)
                elif role == "admin":
                    qs = qs.filter(admin_tenant_q(self.user)).distinct()
                elif role == "secretary":
                    if secretary_can_access_prescriptions():
                        qs = qs.filter(secretary_tenant_q(self.user)).distinct()
                    else:
                        qs = qs.none()
                else:
                    qs = qs.none()

            self.fields["appointment"].queryset = qs.order_by("scheduled_time", "pk")

        # If appointment_id passed for new prescription
        if appointment_id and not self.instance.pk:
            try:
                appt = Appointment.objects.select_related(
                    "patient", "doctor", "doctor__user"
                ).get(pk=appointment_id)

                # ✅ RBAC check for appointment_id
                if self.user and not getattr(self.user, "is_superuser", False):
                    role = getattr(self.user, "role", None)
                    if role == "doctor" and getattr(appt.doctor, "user_id", None) != getattr(self.user, "id", None):
                        raise ValidationError("You cannot use an appointment that is not yours.")
                    if role == "admin" and not appointment_in_admin_scope(self.user, appt):
                        raise ValidationError("You cannot use an appointment outside your assigned scope.")
                    if role == "secretary" and not appointment_in_secretary_scope(self.user, appt):
                        raise ValidationError("You cannot use an appointment outside your assigned scope.")
                    if role not in {"doctor", "secretary", "admin"}:
                        raise ValidationError("You do not have permission to create a prescription.")

                self.initial.setdefault("appointment", appt)
                self.initial.setdefault("patient_full_name", getattr(appt.patient, "full_name", ""))
                self.initial.setdefault("age", getattr(appt.patient, "age", None))

                self.instance.appointment = appt
                self.instance.doctor = appt.doctor

            except Appointment.DoesNotExist:
                logger.warning("Appointment with id=%s not found.", appointment_id)
            except ValidationError:
                # will surface later via clean_appointment/clean
                pass

    def clean_diagnosis(self):
        dx = (self.cleaned_data.get("diagnosis") or "").strip()
        return dx or None  # ✅ خزن None إذا فاضي

    def clean_appointment(self):
        appointment = self.cleaned_data.get("appointment") or getattr(self.instance, "appointment", None)
        if not appointment:
            raise ValidationError("Appointment must be selected.")

        # ✅ RBAC check (extra safety)
        if self.user and not getattr(self.user, "is_superuser", False):
            role = getattr(self.user, "role", None)

            if role == "doctor":
                if getattr(appointment.doctor, "user_id", None) != getattr(self.user, "id", None):
                    raise ValidationError("You cannot use an appointment that is not yours.")
            elif role == "admin":
                if not appointment_in_admin_scope(self.user, appointment):
                    raise ValidationError("You cannot use an appointment outside your assigned scope.")
            elif role == "secretary":
                if not appointment_in_secretary_scope(self.user, appointment):
                    raise ValidationError("You cannot use an appointment outside your assigned scope.")
            else:
                raise ValidationError("You do not have permission to create a prescription.")

        # ✅ Prevent duplicate prescription per appointment
        if Prescription.objects.exclude(pk=self.instance.pk).filter(appointment=appointment).exists():
            raise ValidationError("A prescription already exists for this appointment.")

        return appointment

    def clean(self):
        """
        Always sync patient name & age from appointment.
        """
        cleaned = super().clean()

        appt = cleaned.get("appointment") or getattr(self.instance, "appointment", None)
        if appt and getattr(appt, "patient", None):
            cleaned["patient_full_name"] = getattr(appt.patient, "full_name", "") or ""
            cleaned["age"] = getattr(appt.patient, "age", None)

        return cleaned

    def save(self, commit=True):
        """
        Lock appointment/doctor + patient snapshot before save.
        """
        instance = super().save(commit=False)

        appt = (self.cleaned_data.get("appointment") if hasattr(self, "cleaned_data") else None) or getattr(instance, "appointment", None)

        if appt:
            instance.appointment = appt
            if getattr(appt, "doctor", None):
                instance.doctor = appt.doctor

            if getattr(appt, "patient", None):
                instance.patient_full_name = getattr(appt.patient, "full_name", "") or (instance.patient_full_name or "")
                appt_age = getattr(appt.patient, "age", None)
                if appt_age is not None:
                    instance.age = appt_age

        if commit:
            instance.save()
            self.save_m2m()

        return instance

    def should_archive(self) -> bool:
        return bool(self.cleaned_data.get("archive_prescription"))


MedicationFormSet = inlineformset_factory(
    Prescription,
    Medication,
    fields=("name", "dosage"),
    extra=1,
    can_delete=True,
    min_num=1,
    validate_min=True,
    widgets={
        "name": forms.TextInput(
            attrs={"class": "form-control", "placeholder": "Medication name"}
        ),
        "dosage": forms.TextInput(
            attrs={"class": "form-control", "placeholder": "Dosage"}
        ),
    },
)
