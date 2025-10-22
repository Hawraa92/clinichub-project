# File: prescription/forms.py

from django import forms
from django.forms import inlineformset_factory
from django.core.exceptions import ValidationError
from .models import Prescription, Medication
from appointments.models import Appointment
import logging

logger = logging.getLogger(__name__)

class PrescriptionForm(forms.ModelForm):
    """
    Smart form for creating prescriptions.
    Doctor and patient details are auto-populated from the appointment.
    Includes an option to archive the prescription immediately.
    """
    archive_prescription = forms.BooleanField(
        required=False,
        label="Save to Archive",
        help_text="Automatically archive this prescription for future reference."
    )

    class Meta:
        model = Prescription
        fields = [
            'appointment',
            'patient_full_name',
            'age',
            'instructions',
            'voice_note',
            'doctor_signature',
            'doctor_logo',
            'archive_prescription',
        ]
        widgets = {
            'appointment': forms.Select(attrs={'class': 'form-select'}),
            'patient_full_name': forms.TextInput(attrs={
                'class': 'form-control bg-light',
                'readonly': True
            }),
            'age': forms.NumberInput(attrs={
                'class': 'form-control bg-light',
                'readonly': True
            }),
            'instructions': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 3,
                'placeholder': 'Additional instructions…'
            }),
            'voice_note': forms.ClearableFileInput(attrs={'class': 'form-control'}),
            'doctor_signature': forms.ClearableFileInput(attrs={'class': 'form-control'}),
            'doctor_logo': forms.ClearableFileInput(attrs={'class': 'form-control'}),
        }

    def __init__(self, *args, **kwargs):
        appointment_id = kwargs.pop('appointment_id', None)
        super().__init__(*args, **kwargs)

        if appointment_id:
            try:
                appt = Appointment.objects.select_related('patient', 'doctor').get(pk=appointment_id)
                # ضبط القيم الابتدائية
                self.fields['appointment'].initial = appt
                self.fields['patient_full_name'].initial = appt.patient.full_name
                self.fields['age'].initial = appt.patient.age
                # ربط الطبيب داخل الكائن دون عرضه
                self.instance.doctor = appt.doctor
            except Appointment.DoesNotExist:
                logger.warning(f"Appointment with id={appointment_id} not found.")

        # تعطيل حقول الموعد وبيانات المريض عن التعديل
        for f in ('appointment', 'patient_full_name', 'age'):
            if f in self.fields:
                self.fields[f].disabled = True

    def clean_appointment(self):
        appointment = self.cleaned_data.get('appointment')
        if not appointment:
            raise ValidationError("Appointment must be selected.")
        return appointment

    def clean(self):
        cleaned = super().clean()
        appointment = cleaned.get('appointment')
        if appointment and self.instance.doctor != appointment.doctor:
            raise ValidationError(
                "Mismatch: Doctor in appointment and prescription must be the same."
            )
        return cleaned


# Inline formset for Medication entries
MedicationFormSet = inlineformset_factory(
    Prescription,
    Medication,
    fields=('name', 'dosage'),
    extra=1,
    can_delete=True,
    widgets={
        'name': forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Medication name'
        }),
        'dosage': forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Dosage'
        }),
    }
)
