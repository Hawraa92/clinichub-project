# File: prescription/forms.py
import logging

from django import forms
from django.core.exceptions import ValidationError
from django.forms import inlineformset_factory

from appointments.models import Appointment
from .models import Medication, Prescription

logger = logging.getLogger(__name__)


class PrescriptionForm(forms.ModelForm):
    """
    Smart form for creating/editing prescriptions.

    Key guarantees:
    - Patient snapshot (name/age) always synced from Appointment.patient
    - Doctor always derived from Appointment.doctor
    - RBAC: doctors can only use their own appointments (unless superuser)
    - Prevent duplicate prescriptions per appointment
    - Archive option (form-only): default ON (recommended) but can be unchecked
    """

    # Form-only field (not in model)
    archive_prescription = forms.BooleanField(
        required=False,
        initial=True,  # ✅ recommended default to match "automatic archiving" narrative (optional to opt-out)
        label="Save to Archive",
        help_text="Recommended: also save a copy in the Medical Archive module (if enabled).",
    )

    class Meta:
        model = Prescription
        fields = [
            "appointment",
            "patient_full_name",
            "age",
            "diagnosis",
            "instructions",
            "voice_note",
            "doctor_signature",
            "doctor_logo",
        ]
        widgets = {
            "appointment": forms.Select(attrs={"class": "form-select"}),

            # display-only snapshot fields
            "patient_full_name": forms.TextInput(attrs={"class": "form-control bg-light"}),
            "age": forms.NumberInput(attrs={"class": "form-control bg-light"}),

            "diagnosis": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "Dx / Diagnosis… (e.g., Acute pharyngitis / GERD / PCOS)",
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
        self.user = kwargs.pop("user", None)
        appointment_id = kwargs.pop("appointment_id", None)
        super().__init__(*args, **kwargs)

        # checkbox styling
        self.fields["archive_prescription"].widget.attrs.update({"class": "form-check-input"})

        # patient snapshot fields are display-only
        self.fields["patient_full_name"].required = False
        self.fields["age"].required = False
        self.fields["patient_full_name"].disabled = True
        self.fields["age"].disabled = True

        # Dx optional
        if "diagnosis" in self.fields:
            self.fields["diagnosis"].required = False

        # Build appointment queryset with RBAC + safety filters
        if "appointment" in self.fields:
            qs = Appointment.objects.select_related("patient", "doctor", "doctor__user")

            # Optional: exclude cancelled appointments (safe if field exists)
            if hasattr(Appointment, "status"):
                qs = qs.exclude(status="cancelled")

            # RBAC
            qs = self._restrict_appointments_qs(qs)

            # For CREATE: exclude appointments already used by any prescription
            # For EDIT: allow the current appointment even if already used (it is used by this instance)
            if not self.instance.pk:
                try:
                    used_ids = (
                        Prescription.objects.exclude(appointment_id__isnull=True)
                        .values_list("appointment_id", flat=True)
                    )
                    qs = qs.exclude(id__in=used_ids)
                except Exception:
                    pass

            self.fields["appointment"].queryset = qs.order_by("scheduled_time", "pk")

        # If appointment_id passed (typical when create page pre-selects an appointment)
        if appointment_id and not self.instance.pk:
            self._apply_forced_appointment(appointment_id)

        # If editing and we have an instance appointment, ensure snapshot shown
        if self.instance.pk and getattr(self.instance, "appointment_id", None):
            self._sync_snapshot_from_appointment(getattr(self.instance, "appointment", None))

    # -------------------------
    # Helpers
    # -------------------------
    def _role(self) -> str:
        return str(getattr(self.user, "role", "") or "").lower()

    def _restrict_appointments_qs(self, qs):
        """
        Doctors -> only their appointments.
        Superuser -> all.
        Others -> none (creation is doctor-only anyway; views enforce too).
        """
        if not self.user or not getattr(self.user, "is_authenticated", False):
            return qs.none()

        if getattr(self.user, "is_superuser", False):
            return qs

        role = self._role()
        if role == "doctor":
            return qs.filter(doctor__user=self.user)

        # keep strict here (views already forbid, but form stays safe)
        return qs.none()

    def _apply_forced_appointment(self, appointment_id: int) -> None:
        """
        Pre-select appointment and lock instance.doctor accordingly.
        """
        try:
            # Prefer using the already restricted queryset to avoid leaking appointments
            field_qs = self.fields["appointment"].queryset if "appointment" in self.fields else None
            appt = (field_qs.filter(pk=appointment_id).first() if field_qs is not None else None)

            if appt is None:
                # Fallback (still RBAC validated below)
                appt = Appointment.objects.select_related("patient", "doctor", "doctor__user").get(pk=appointment_id)

            # RBAC hard check (even in fallback)
            if self.user and not getattr(self.user, "is_superuser", False):
                if self._role() == "doctor" and getattr(appt.doctor, "user_id", None) != getattr(self.user, "id", None):
                    raise ValidationError("You cannot use an appointment that is not yours.")

            self.initial.setdefault("appointment", appt)
            self._sync_snapshot_from_appointment(appt)

            self.instance.appointment = appt
            self.instance.doctor = appt.doctor

        except Appointment.DoesNotExist:
            logger.warning("Appointment with id=%s not found.", appointment_id)
        except ValidationError:
            # surfaced later in clean_appointment
            pass
        except Exception as e:
            logger.warning("Failed applying forced appointment id=%s: %s", appointment_id, e)

    def _sync_snapshot_from_appointment(self, appt: Appointment | None) -> None:
        if not appt or not getattr(appt, "patient", None):
            return
        self.initial.setdefault("patient_full_name", getattr(appt.patient, "full_name", "") or "")
        self.initial.setdefault("age", getattr(appt.patient, "age", None))

    # -------------------------
    # Cleaning
    # -------------------------
    def clean_diagnosis(self):
        dx = (self.cleaned_data.get("diagnosis") or "").strip()
        return dx or None

    def clean_appointment(self):
        appointment = self.cleaned_data.get("appointment") or getattr(self.instance, "appointment", None)
        if not appointment:
            raise ValidationError("Appointment must be selected.")

        # Prevent using cancelled appointment (if field exists)
        if hasattr(appointment, "status"):
            st = str(getattr(appointment, "status", "") or "").lower()
            if st == "cancelled":
                raise ValidationError("You cannot issue a prescription for a cancelled appointment.")

        # RBAC check
        if self.user and not getattr(self.user, "is_superuser", False):
            if self._role() == "doctor":
                if getattr(appointment.doctor, "user_id", None) != getattr(self.user, "id", None):
                    raise ValidationError("You cannot use an appointment that is not yours.")
            else:
                raise ValidationError("You do not have permission to create a prescription.")

        # Prevent duplicate prescription per appointment
        if Prescription.objects.exclude(pk=self.instance.pk).filter(appointment=appointment).exists():
            raise ValidationError("A prescription already exists for this appointment.")

        return appointment

    def clean(self):
        """
        Always sync patient name & age from appointment into cleaned_data (display only).
        """
        cleaned = super().clean()
        appt = cleaned.get("appointment") or getattr(self.instance, "appointment", None)

        if appt and getattr(appt, "patient", None):
            cleaned["patient_full_name"] = getattr(appt.patient, "full_name", "") or ""
            cleaned["age"] = getattr(appt.patient, "age", None)

        return cleaned

    # -------------------------
    # Saving
    # -------------------------
    def save(self, commit=True):
        """
        Lock appointment/doctor + patient snapshot before save.
        """
        instance: Prescription = super().save(commit=False)

        appt = self.cleaned_data.get("appointment") if hasattr(self, "cleaned_data") else None
        appt = appt or getattr(instance, "appointment", None)

        if appt:
            instance.appointment = appt

            # doctor must match appointment.doctor
            if getattr(appt, "doctor", None):
                instance.doctor = appt.doctor

            # snapshot patient fields
            if getattr(appt, "patient", None):
                instance.patient_full_name = (
                    getattr(appt.patient, "full_name", "") or (instance.patient_full_name or "")
                )
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
        "name": forms.TextInput(attrs={"class": "form-control", "placeholder": "Medication name"}),
        "dosage": forms.TextInput(attrs={"class": "form-control", "placeholder": "Dosage"}),
    },
)
