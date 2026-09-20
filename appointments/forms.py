from __future__ import annotations

from datetime import timedelta

from django import forms
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db.models import Q
from django.utils import timezone
from django.utils.timezone import get_default_timezone, localtime, make_aware
from django.utils.translation import gettext_lazy as _

from doctor.models import Doctor
from hospital.models import Branch, Department, Hospital, StaffAssignment
from patient.models import Patient

from .models import (
    Appointment,
    AppointmentStatus,
    PAST_MARGIN,
    PatientBookingRequest,
)


_LOCAL_TZ = get_default_timezone()


def _model_has_field(model, field_name: str) -> bool:
    try:
        return any(
            getattr(field, "name", "") == field_name
            for field in model._meta.get_fields()
        )
    except Exception:
        return False


def _to_local_aware(value):
    if value is None:
        return None

    if timezone.is_naive(value):
        return make_aware(value, _LOCAL_TZ)

    return value.astimezone(_LOCAL_TZ)


def _default_staff_status():
    for name in ("APPROVED", "CONFIRMED", "ACCEPTED"):
        if hasattr(AppointmentStatus, name):
            return getattr(AppointmentStatus, name)

    return AppointmentStatus.PENDING


def _selected_id(form, field_name: str):
    if form.is_bound:
        value = form.data.get(form.add_prefix(field_name))
        return value or None

    if getattr(form, "instance", None) and form.instance.pk:
        value = getattr(form.instance, f"{field_name}_id", None)
        if value:
            return value

    value = form.initial.get(field_name)

    if hasattr(value, "pk"):
        return value.pk

    return value or None


def _primary_doctor_assignment(doctor):
    if not doctor or not getattr(doctor, "user_id", None):
        return None

    return (
        StaffAssignment.objects.select_related(
            "hospital",
            "branch",
            "department",
        )
        .filter(
            user_id=doctor.user_id,
            role=StaffAssignment.Roles.DOCTOR,
            is_active=True,
        )
        .order_by("-is_primary", "pk")
        .first()
    )


def _configure_location_querysets(form):
    hospital_id = _selected_id(form, "hospital")
    branch_id = _selected_id(form, "branch")
    department_id = _selected_id(form, "department")

    if "hospital" in form.fields:
        hospital_queryset = Hospital.objects.filter(is_active=True)

        if hospital_id:
            hospital_queryset = Hospital.objects.filter(
                Q(is_active=True) | Q(pk=hospital_id)
            )

        form.fields["hospital"].queryset = hospital_queryset.order_by("name")

    if "branch" in form.fields:
        branch_queryset = Branch.objects.select_related("hospital").filter(
            is_active=True
        )

        if hospital_id:
            branch_queryset = branch_queryset.filter(hospital_id=hospital_id)

        if branch_id:
            branch_queryset = Branch.objects.select_related("hospital").filter(
                Q(is_active=True) | Q(pk=branch_id)
            )

            if hospital_id:
                branch_queryset = branch_queryset.filter(
                    hospital_id=hospital_id
                )

        form.fields["branch"].queryset = branch_queryset.order_by(
            "hospital__name",
            "name",
        )

    if "department" in form.fields:
        department_queryset = Department.objects.select_related(
            "branch",
            "branch__hospital",
        ).filter(is_active=True)

        if branch_id:
            department_queryset = department_queryset.filter(
                branch_id=branch_id
            )

        if department_id:
            department_queryset = Department.objects.select_related(
                "branch",
                "branch__hospital",
            ).filter(
                Q(is_active=True) | Q(pk=department_id)
            )

            if branch_id:
                department_queryset = department_queryset.filter(
                    branch_id=branch_id
                )

        form.fields["department"].queryset = department_queryset.order_by(
            "branch__hospital__name",
            "branch__name",
            "name",
        )


def _apply_and_validate_location(form, cleaned):
    doctor = cleaned.get("doctor")
    hospital = cleaned.get("hospital")
    branch = cleaned.get("branch")
    department = cleaned.get("department")

    assignment = _primary_doctor_assignment(doctor)

    if assignment:
        if hospital is None:
            hospital = assignment.hospital
            cleaned["hospital"] = hospital

        if branch is None and assignment.branch_id:
            branch = assignment.branch
            cleaned["branch"] = branch

        if department is None and assignment.department_id:
            department = assignment.department
            cleaned["department"] = department

    if hospital and not hospital.is_active:
        form.add_error(
            "hospital",
            _("The selected hospital is inactive."),
        )

    if branch and not branch.is_active:
        form.add_error(
            "branch",
            _("The selected branch is inactive."),
        )

    if department and not department.is_active:
        form.add_error(
            "department",
            _("The selected department is inactive."),
        )

    if branch and hospital and branch.hospital_id != hospital.id:
        form.add_error(
            "branch",
            _("The selected branch does not belong to the selected hospital."),
        )

    if department:
        if not branch:
            form.add_error(
                "branch",
                _("A branch is required when a department is selected."),
            )
        elif department.branch_id != branch.id:
            form.add_error(
                "department",
                _("The selected department does not belong to the selected branch."),
            )

    if doctor and hospital:
        assignments = StaffAssignment.objects.filter(
            user_id=doctor.user_id,
            role=StaffAssignment.Roles.DOCTOR,
            hospital_id=hospital.id,
            is_active=True,
        )

        if branch:
            assignments = assignments.filter(branch_id=branch.id)

        if department:
            assignments = assignments.filter(department_id=department.id)

        if not assignments.exists():
            form.add_error(
                "doctor",
                _(
                    "This doctor does not have an active assignment "
                    "at the selected location."
                ),
            )

    return cleaned


class DateTimeLocalInput(forms.DateTimeInput):
    input_type = "datetime-local"
    format = "%Y-%m-%dT%H:%M"

    def __init__(self, **kwargs):
        attrs = kwargs.pop("attrs", {})
        base_attrs = {
            "class": "form-control",
            "step": "60",
        }
        base_attrs.update(attrs)

        super().__init__(
            attrs=base_attrs,
            format=self.format,
        )


class DateInput(forms.DateInput):
    input_type = "date"
    format = "%Y-%m-%d"

    def __init__(self, **kwargs):
        attrs = kwargs.pop("attrs", {})
        base_attrs = {"class": "form-control"}
        base_attrs.update(attrs)

        super().__init__(
            attrs=base_attrs,
            format=self.format,
        )


_BASE_DT_INPUT_FORMATS = [
    DateTimeLocalInput.format,
    "%Y-%m-%d %H:%M",
    "%Y-%m-%d %I:%M %p",
]

try:
    _EXTRA_DT_INPUT_FORMATS = list(
        getattr(settings, "DATETIME_INPUT_FORMATS", [])
    )
except Exception:
    _EXTRA_DT_INPUT_FORMATS = []

DATETIME_INPUT_FORMATS = _BASE_DT_INPUT_FORMATS + [
    input_format
    for input_format in _EXTRA_DT_INPUT_FORMATS
    if input_format not in _BASE_DT_INPUT_FORMATS
]


_APPOINTMENT_META_FIELDS: list[str] = [
    "patient",
    "hospital",
    "branch",
    "department",
    "doctor",
    "scheduled_time",
]

if _model_has_field(Appointment, "status"):
    _APPOINTMENT_META_FIELDS.append("status")

if _model_has_field(Appointment, "iqd_amount"):
    _APPOINTMENT_META_FIELDS.append("iqd_amount")

if _model_has_field(Appointment, "notes"):
    _APPOINTMENT_META_FIELDS.append("notes")


class AppointmentForm(forms.ModelForm):
    scheduled_time = forms.DateTimeField(
        widget=DateTimeLocalInput(),
        input_formats=DATETIME_INPUT_FORMATS,
        label=_("Appointment Time"),
        help_text=_("Must be a future time in the local timezone."),
    )

    if _model_has_field(Appointment, "status"):
        status = forms.ChoiceField(
            choices=AppointmentStatus.choices,
            widget=forms.Select(
                attrs={"class": "form-select"}
            ),
            label=_("Status"),
        )

    if _model_has_field(Appointment, "iqd_amount"):
        iqd_amount = forms.DecimalField(
            max_digits=15,
            decimal_places=0,
            min_value=0,
            required=False,
            label=_("Amount (IQD)"),
            widget=forms.NumberInput(
                attrs={
                    "class": "form-control",
                    "placeholder": _("Amount in IQD"),
                }
            ),
            help_text=_("Optional. Defaults to 0 if left blank."),
        )

    if _model_has_field(Appointment, "notes"):
        notes = forms.CharField(
            required=False,
            label=_("Notes"),
            widget=forms.Textarea(
                attrs={
                    "class": "form-control",
                    "rows": 2,
                    "placeholder": _("Optional notes"),
                }
            ),
        )

    class Meta:
        model = Appointment
        fields = _APPOINTMENT_META_FIELDS
        widgets = {
            "patient": forms.Select(
                attrs={"class": "form-select"}
            ),
            "hospital": forms.Select(
                attrs={"class": "form-select"}
            ),
            "branch": forms.Select(
                attrs={"class": "form-select"}
            ),
            "department": forms.Select(
                attrs={"class": "form-select"}
            ),
            "doctor": forms.Select(
                attrs={"class": "form-select"}
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        if "patient" in self.fields:
            self.fields["patient"].queryset = Patient.objects.order_by(
                "full_name"
            )

        if "doctor" in self.fields:
            self.fields["doctor"].queryset = (
                Doctor.objects.select_related("user")
                .order_by(
                    "full_name",
                    "user__first_name",
                    "user__last_name",
                )
            )

            self.fields["doctor"].label_from_instance = (
                lambda doctor: (
                    doctor.full_name
                    or doctor.user.get_full_name()
                    or doctor.user.username
                    or doctor.user.email
                )
            )

        _configure_location_querysets(self)

        if (
            "status" in self.fields
            and not self.instance.pk
            and not self.is_bound
        ):
            self.initial["status"] = _default_staff_status()

        if self.instance.pk and "iqd_amount" in self.fields:
            amount = getattr(self.instance, "iqd_amount", None)

            if amount is not None:
                self.initial["iqd_amount"] = amount

        if not self.is_bound:
            doctor_id = _selected_id(self, "doctor")

            if doctor_id:
                doctor = (
                    Doctor.objects.select_related("user")
                    .filter(pk=doctor_id)
                    .first()
                )
                assignment = _primary_doctor_assignment(doctor)

                if assignment:
                    self.initial.setdefault(
                        "hospital",
                        assignment.hospital_id,
                    )

                    if assignment.branch_id:
                        self.initial.setdefault(
                            "branch",
                            assignment.branch_id,
                        )

                    if assignment.department_id:
                        self.initial.setdefault(
                            "department",
                            assignment.department_id,
                        )

    def clean_scheduled_time(self):
        value = self.cleaned_data.get("scheduled_time")

        if not value:
            return value

        aware_value = _to_local_aware(value)

        if aware_value < localtime() - PAST_MARGIN:
            raise ValidationError(
                _("The selected time is in the past.")
            )

        return aware_value

    def clean(self):
        cleaned = super().clean()

        doctor = cleaned.get("doctor")
        scheduled_time = cleaned.get("scheduled_time")

        if scheduled_time:
            scheduled_time = _to_local_aware(scheduled_time)
            cleaned["scheduled_time"] = scheduled_time

        gap_minutes = int(
            getattr(
                settings,
                "APPOINTMENT_GAP_MINUTES",
                1,
            )
            or 1
        )

        if doctor and scheduled_time:
            window_start = scheduled_time - timedelta(
                minutes=gap_minutes
            )
            window_end = scheduled_time + timedelta(
                minutes=gap_minutes
            )

            appointments = Appointment.objects.filter(
                doctor=doctor
            ).exclude(pk=self.instance.pk)

            if hasattr(AppointmentStatus, "CANCELLED"):
                appointments = appointments.exclude(
                    status=AppointmentStatus.CANCELLED
                )

            overlapping = appointments.filter(
                scheduled_time__gt=window_start,
                scheduled_time__lt=window_end,
            ).exists()

            if overlapping:
                raise ValidationError(
                    _(
                        "At least %(minutes)s minute(s) are required "
                        "between appointments for the same doctor."
                    ),
                    params={"minutes": gap_minutes},
                )

        if (
            "iqd_amount" in cleaned
            and cleaned.get("iqd_amount") in (None, "")
        ):
            cleaned["iqd_amount"] = 0

        return _apply_and_validate_location(self, cleaned)


class PatientBookingForm(forms.ModelForm):
    full_name = forms.CharField(
        max_length=100,
        label=_("Your Full Name"),
        widget=forms.TextInput(
            attrs={
                "class": "form-control",
                "placeholder": _("Enter your full name"),
            }
        ),
    )

    contact_info = forms.CharField(
        max_length=200,
        label=_("Phone / Contact"),
        widget=forms.TextInput(
            attrs={
                "class": "form-control",
                "placeholder": _("Your phone number"),
            }
        ),
        help_text=_("We will use this to contact you."),
    )

    date_of_birth = forms.DateField(
        required=False,
        label=_("Your Date of Birth"),
        widget=DateInput(),
        input_formats=[DateInput.format],
    )

    scheduled_time = forms.DateTimeField(
        widget=DateTimeLocalInput(),
        input_formats=DATETIME_INPUT_FORMATS,
        label=_("Preferred Time"),
        help_text=_("Must be a future time in the local timezone."),
    )

    class Meta:
        model = PatientBookingRequest
        fields = [
            "full_name",
            "date_of_birth",
            "contact_info",
            "hospital",
            "branch",
            "department",
            "doctor",
            "scheduled_time",
        ]
        widgets = {
            "hospital": forms.Select(
                attrs={"class": "form-select"}
            ),
            "branch": forms.Select(
                attrs={"class": "form-select"}
            ),
            "department": forms.Select(
                attrs={"class": "form-select"}
            ),
            "doctor": forms.Select(
                attrs={"class": "form-select"}
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        if "doctor" in self.fields:
            self.fields["doctor"].queryset = (
                Doctor.objects.select_related("user")
                .filter(available=True)
                .order_by(
                    "full_name",
                    "user__first_name",
                    "user__last_name",
                )
            )

            self.fields["doctor"].label_from_instance = (
                lambda doctor: (
                    doctor.full_name
                    or doctor.user.get_full_name()
                    or doctor.user.username
                    or doctor.user.email
                )
            )

        _configure_location_querysets(self)

        if not self.is_bound:
            doctor_id = _selected_id(self, "doctor")

            if doctor_id:
                doctor = (
                    Doctor.objects.select_related("user")
                    .filter(pk=doctor_id)
                    .first()
                )
                assignment = _primary_doctor_assignment(doctor)

                if assignment:
                    self.initial.setdefault(
                        "hospital",
                        assignment.hospital_id,
                    )

                    if assignment.branch_id:
                        self.initial.setdefault(
                            "branch",
                            assignment.branch_id,
                        )

                    if assignment.department_id:
                        self.initial.setdefault(
                            "department",
                            assignment.department_id,
                        )

    def clean_scheduled_time(self):
        value = self.cleaned_data.get("scheduled_time")

        if not value:
            return value

        aware_value = _to_local_aware(value)

        if aware_value < localtime() - PAST_MARGIN:
            raise ValidationError(
                _("Please choose a future time.")
            )

        return aware_value

    def clean(self):
        cleaned = super().clean()

        doctor = cleaned.get("doctor")
        scheduled_time = cleaned.get("scheduled_time")

        if scheduled_time:
            scheduled_time = _to_local_aware(scheduled_time)
            cleaned["scheduled_time"] = scheduled_time

        if doctor and scheduled_time:
            appointments = Appointment.objects.filter(
                doctor_id=doctor.id,
                scheduled_time=scheduled_time,
            )

            if hasattr(AppointmentStatus, "CANCELLED"):
                appointments = appointments.exclude(
                    status=AppointmentStatus.CANCELLED
                )

            if appointments.exists():
                raise ValidationError(
                    _(
                        "This time is already allocated "
                        "for this doctor."
                    )
                )

        return _apply_and_validate_location(self, cleaned)
