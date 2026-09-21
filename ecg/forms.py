from django import forms

from .models import ECGRecord


class ECGRecordForm(forms.ModelForm):
    class Meta:
        model = ECGRecord

        fields = [
            "patient",
            "doctor",
            "appointment",
            "hospital",
            "branch",
            "department",
            "recorded_at",
            "device_manufacturer",
            "device_model",
            "sampling_frequency_hz",
            "lead_count",
            "duration_seconds",
            "notes",
        ]

        widgets = {
            "patient": forms.Select(
                attrs={
                    "class": "form-select",
                }
            ),
            "doctor": forms.Select(
                attrs={
                    "class": "form-select",
                }
            ),
            "appointment": forms.Select(
                attrs={
                    "class": "form-select",
                }
            ),
            "hospital": forms.Select(
                attrs={
                    "class": "form-select",
                }
            ),
            "branch": forms.Select(
                attrs={
                    "class": "form-select",
                }
            ),
            "department": forms.Select(
                attrs={
                    "class": "form-select",
                }
            ),
            "recorded_at": forms.DateTimeInput(
                format="%Y-%m-%dT%H:%M",
                attrs={
                    "class": "form-control",
                    "type": "datetime-local",
                },
            ),
            "device_manufacturer": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "Device manufacturer",
                }
            ),
            "device_model": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "Device model",
                }
            ),
            "sampling_frequency_hz": forms.NumberInput(
                attrs={
                    "class": "form-control",
                    "min": "1",
                }
            ),
            "lead_count": forms.NumberInput(
                attrs={
                    "class": "form-control",
                    "min": "1",
                }
            ),
            "duration_seconds": forms.NumberInput(
                attrs={
                    "class": "form-control",
                    "min": "0",
                    "step": "0.01",
                }
            ),
            "notes": forms.Textarea(
                attrs={
                    "class": "form-control",
                    "rows": 4,
                    "placeholder": "Optional ECG notes",
                }
            ),
        }

    def __init__(
        self,
        *args,
        patient_queryset=None,
        doctor_queryset=None,
        appointment_queryset=None,
        hospital_queryset=None,
        branch_queryset=None,
        department_queryset=None,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)

        self.fields["recorded_at"].input_formats = [
            "%Y-%m-%dT%H:%M",
        ]

        scoped_querysets = {
            "patient": patient_queryset,
            "doctor": doctor_queryset,
            "appointment": appointment_queryset,
            "hospital": hospital_queryset,
            "branch": branch_queryset,
            "department": department_queryset,
        }

        for field_name, queryset in scoped_querysets.items():
            if queryset is None:
                self.fields[field_name].queryset = (
                    self.fields[field_name]
                    .queryset
                    .none()
                )
            else:
                self.fields[field_name].queryset = queryset

        self.fields["appointment"].required = False
        self.fields["hospital"].required = False
        self.fields["branch"].required = False
        self.fields["department"].required = False