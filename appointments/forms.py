# appointments/forms.py
from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

from django import forms
from django.conf import settings
from django.core.exceptions import ValidationError
from django.utils import timezone
from django.utils.timezone import get_default_timezone, make_aware
from django.utils.translation import gettext_lazy as _

from doctor.models import Doctor
from patient.models import Patient

from .models import Appointment, AppointmentStatus, PatientBookingRequest

# =============================
# Helpers / Time normalization
# =============================
_LOCAL_TZ = get_default_timezone()


def _use_tz() -> bool:
    return bool(getattr(settings, "USE_TZ", False))


def _model_has_field(model, field_name: str) -> bool:
    try:
        model._meta.get_field(field_name)  # type: ignore[attr-defined]
        return True
    except Exception:
        return False


# Prefer using same constant name as your models.py if it exists
try:  # pragma: no cover
    from .models import PAST_MARGIN as _PAST_MARGIN  # type: ignore
except Exception:  # pragma: no cover
    try:
        from .models import PAST_TOLERANCE as _PAST_MARGIN  # type: ignore
    except Exception:
        _PAST_MARGIN = timedelta(seconds=60)


def _now_local() -> datetime:
    """
    Now in same representation we expect for normalized datetimes:
    - USE_TZ=True  -> aware in LOCAL_TZ
    - USE_TZ=False -> naive local wall-clock
    """
    now = timezone.now()
    if _use_tz():
        if timezone.is_naive(now):
            now = make_aware(now, _LOCAL_TZ)
        return timezone.localtime(now, _LOCAL_TZ)

    # USE_TZ=False
    if timezone.is_aware(now):
        return timezone.localtime(now, _LOCAL_TZ).replace(tzinfo=None)
    return now


def _normalize_dt(dt: datetime | None) -> datetime | None:
    """
    Normalize dt consistent with project behavior:
    - USE_TZ=True  -> return aware dt in LOCAL_TZ
    - USE_TZ=False -> return naive local wall-clock
    """
    if dt is None:
        return None

    if _use_tz():
        if timezone.is_naive(dt):
            return make_aware(dt, _LOCAL_TZ)
        return timezone.localtime(dt, _LOCAL_TZ)

    # USE_TZ=False
    if timezone.is_aware(dt):
        return timezone.localtime(dt, _LOCAL_TZ).replace(tzinfo=None)
    return dt


def _is_past(dt: datetime | None) -> bool:
    nd = _normalize_dt(dt)
    if nd is None:
        return False
    return nd < (_now_local() - _PAST_MARGIN)


def _cancelled_status_value():
    """
    Return CANCELLED value if available, else None.
    """
    if hasattr(AppointmentStatus, "CANCELLED"):
        return getattr(AppointmentStatus, "CANCELLED")
    return None


def _status_choices():
    """
    Robustly resolve status choices.
    """
    if hasattr(AppointmentStatus, "choices"):
        try:
            return AppointmentStatus.choices  # type: ignore[attr-defined]
        except Exception:
            pass
    if hasattr(Appointment, "STATUS_CHOICES"):
        return getattr(Appointment, "STATUS_CHOICES")
    # Fallback (minimal)
    return [
        ("pending", "Pending"),
        ("completed", "Completed"),
        ("cancelled", "Cancelled"),
    ]


def _default_staff_status():
    for name in ("APPROVED", "CONFIRMED", "ACCEPTED"):
        if hasattr(AppointmentStatus, name):
            return getattr(AppointmentStatus, name)
    return getattr(AppointmentStatus, "PENDING", "pending")


# =============================
# Widgets
# =============================
class DateTimeLocalInput(forms.DateTimeInput):
    input_type = "datetime-local"
    format = "%Y-%m-%dT%H:%M"

    def __init__(self, **kwargs):
        attrs = kwargs.pop("attrs", {})
        base = {"class": "form-control", "step": "60"}
        base.update(attrs)
        super().__init__(attrs=base, format=self.format)


class DateInput(forms.DateInput):
    input_type = "date"
    format = "%Y-%m-%d"

    def __init__(self, **kwargs):
        attrs = kwargs.pop("attrs", {})
        base = {"class": "form-control"}
        base.update(attrs)
        super().__init__(attrs=base, format=self.format)


# Accepted datetime input formats
_BASE_DT_INPUT_FORMATS = [
    DateTimeLocalInput.format,  # 2025-11-29T08:00
    "%Y-%m-%d %H:%M",           # 2025-11-29 08:00
    "%Y-%m-%d %I:%M %p",        # 2025-11-29 8:00 AM
]

try:
    _EXTRA_DT_INPUT_FORMATS = list(getattr(settings, "DATETIME_INPUT_FORMATS", []))
except Exception:
    _EXTRA_DT_INPUT_FORMATS = []

DATETIME_INPUT_FORMATS = _BASE_DT_INPUT_FORMATS + [f for f in _EXTRA_DT_INPUT_FORMATS if f not in _BASE_DT_INPUT_FORMATS]


# =============================
# Appointment Form (Staff)
# =============================
_APPOINTMENT_META_FIELDS: list[str] = ["patient", "doctor", "scheduled_time"]
if _model_has_field(Appointment, "status"):
    _APPOINTMENT_META_FIELDS.append("status")
if _model_has_field(Appointment, "iqd_amount"):
    _APPOINTMENT_META_FIELDS.append("iqd_amount")
if _model_has_field(Appointment, "notes"):
    _APPOINTMENT_META_FIELDS.append("notes")


class AppointmentForm(forms.ModelForm):
    """
    Staff create/edit appointment.
    - Prevent past booking (with tolerance)
    - Enforce per-doctor gap window around the slot
    - Exclude CANCELLED from conflicts
    """

    scheduled_time = forms.DateTimeField(
        widget=DateTimeLocalInput(),
        input_formats=DATETIME_INPUT_FORMATS,
        label=_("Appointment Time"),
        help_text=_("Must be a future time (local)."),
        required=True,
    )

    if _model_has_field(Appointment, "status"):
        status = forms.ChoiceField(
            choices=_status_choices(),
            widget=forms.Select(attrs={"class": "form-select"}),
            label=_("Status"),
            required=True,
        )

    if _model_has_field(Appointment, "iqd_amount"):
        iqd_amount = forms.DecimalField(
            max_digits=15,
            decimal_places=0,
            min_value=0,
            required=False,
            label=_("Amount (IQD)"),
            widget=forms.NumberInput(attrs={"class": "form-control", "placeholder": _("Amount in IQD")}),
            help_text=_("Optional. Defaults to 0 if left blank."),
        )

    if _model_has_field(Appointment, "notes"):
        notes = forms.CharField(
            required=False,
            label=_("Notes"),
            widget=forms.Textarea(attrs={"class": "form-control", "rows": 2, "placeholder": _("Optional notes")}),
        )

    class Meta:
        model = Appointment
        fields = _APPOINTMENT_META_FIELDS
        widgets = {
            "patient": forms.Select(attrs={"class": "form-select"}),
            "doctor": forms.Select(attrs={"class": "form-select"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        if "patient" in self.fields:
            if _model_has_field(Patient, "full_name"):
                self.fields["patient"].queryset = Patient.objects.order_by("full_name")
            else:
                self.fields["patient"].queryset = Patient.objects.order_by("id")

        if "doctor" in self.fields:
            self.fields["doctor"].queryset = Doctor.objects.select_related("user").order_by(
                "user__first_name", "user__last_name"
            )
            self.fields["doctor"].label_from_instance = (
                lambda obj: getattr(obj, "full_name", None) or obj.user.get_full_name() or obj.user.username
            )

        # Default status for new appointment
        if "status" in self.fields and not self.instance.pk and not self.is_bound:
            self.initial.setdefault("status", _default_staff_status())

        # Keep existing amount visible
        if self.instance.pk and "iqd_amount" in self.fields:
            val = getattr(self.instance, "iqd_amount", None)
            if val is not None:
                self.initial["iqd_amount"] = val

    def clean_scheduled_time(self):
        dt = self.cleaned_data.get("scheduled_time")
        nd = _normalize_dt(dt)
        if nd and _is_past(nd):
            raise ValidationError(_("The selected time is in the past."))
        return nd

    def clean(self):
        cleaned = super().clean()

        doctor = cleaned.get("doctor")
        scheduled_time = cleaned.get("scheduled_time")
        scheduled_time = _normalize_dt(scheduled_time) if scheduled_time else None
        if scheduled_time:
            cleaned["scheduled_time"] = scheduled_time

        # Default amount to 0
        if "iqd_amount" in cleaned and cleaned.get("iqd_amount") in (None, ""):
            cleaned["iqd_amount"] = 0

        gap_min = int(getattr(settings, "APPOINTMENT_GAP_MINUTES", 1) or 1)
        gap_min = max(0, gap_min)

        if doctor and scheduled_time:
            window_start = scheduled_time - timedelta(minutes=gap_min)
            window_end = scheduled_time + timedelta(minutes=gap_min)

            qs = Appointment.objects.filter(doctor=doctor).exclude(pk=self.instance.pk)

            cancelled_val = _cancelled_status_value()
            if cancelled_val is not None and _model_has_field(Appointment, "status"):
                qs = qs.exclude(status=cancelled_val)

            # overlap within (start, end)
            overlapping = qs.filter(scheduled_time__gt=window_start, scheduled_time__lt=window_end).exists()
            if overlapping:
                raise ValidationError(
                    _("A gap of %(mins)s minute(s) is required between appointments for the same doctor.")
                    % {"mins": gap_min}
                )

        return cleaned


# =============================
# Public Booking Form (Visitors)
# =============================
_BOOKING_META_FIELDS: list[str] = []
for f in ("full_name", "date_of_birth", "contact_info", "doctor", "scheduled_time"):
    if _model_has_field(PatientBookingRequest, f):
        _BOOKING_META_FIELDS.append(f)

_BOOKING_WIDGETS: dict[str, forms.Widget] = {}
if _model_has_field(PatientBookingRequest, "doctor"):
    _BOOKING_WIDGETS["doctor"] = forms.Select(attrs={"class": "form-select"})


class PatientBookingForm(forms.ModelForm):
    """
    Public booking request form (no login).
    Supports optional locked_doctor to restrict choices.
    """

    if _model_has_field(PatientBookingRequest, "full_name"):
        full_name = forms.CharField(
            max_length=100,
            label=_("Your Full Name"),
            widget=forms.TextInput(attrs={"class": "form-control", "placeholder": _("Enter your full name")}),
        )

    if _model_has_field(PatientBookingRequest, "contact_info"):
        contact_info = forms.CharField(
            max_length=200,
            label=_("Phone / Contact"),
            widget=forms.TextInput(attrs={"class": "form-control", "placeholder": _("Your phone number")}),
            help_text=_("We will use this to contact you."),
        )

    if _model_has_field(PatientBookingRequest, "date_of_birth"):
        date_of_birth = forms.DateField(
            required=False,
            label=_("Your Date of Birth"),
            widget=DateInput(),
            input_formats=[DateInput.format],
        )

    if _model_has_field(PatientBookingRequest, "scheduled_time"):
        scheduled_time = forms.DateTimeField(
            widget=DateTimeLocalInput(),
            input_formats=DATETIME_INPUT_FORMATS,
            label=_("Preferred Time"),
            help_text=_("Must be a future time (local)."),
            required=True,
        )

    class Meta:
        model = PatientBookingRequest
        fields = _BOOKING_META_FIELDS
        widgets = _BOOKING_WIDGETS

    def __init__(self, *args, locked_doctor: Doctor | None = None, **kwargs):
        super().__init__(*args, **kwargs)
        self.locked_doctor = locked_doctor

        if "doctor" in self.fields:
            qs = Doctor.objects.select_related("user").order_by("user__first_name", "user__last_name")
            if locked_doctor is not None:
                qs = qs.filter(pk=locked_doctor.pk)
                self.fields["doctor"].initial = locked_doctor.pk
                self.fields["doctor"].disabled = True
            self.fields["doctor"].queryset = qs
            self.fields["doctor"].label_from_instance = (
                lambda obj: getattr(obj, "full_name", None) or obj.user.get_full_name() or obj.user.username
            )

    def clean_scheduled_time(self):
        dt = self.cleaned_data.get("scheduled_time")
        nd = _normalize_dt(dt)
        if nd and _is_past(nd):
            raise ValidationError(_("Please choose a future time."))
        return nd

    def clean(self):
        cleaned = super().clean()

        # Enforce locked doctor if passed
        if self.locked_doctor is not None and "doctor" in self.fields:
            cleaned["doctor"] = self.locked_doctor

        doctor = cleaned.get("doctor")
        scheduled_time = cleaned.get("scheduled_time")
        scheduled_time = _normalize_dt(scheduled_time) if scheduled_time else None
        if scheduled_time:
            cleaned["scheduled_time"] = scheduled_time

        # Quick conflict check against actual appointments
        if doctor and scheduled_time:
            qs = Appointment.objects.filter(doctor_id=getattr(doctor, "id", doctor), scheduled_time=scheduled_time)

            cancelled_val = _cancelled_status_value()
            if cancelled_val is not None and _model_has_field(Appointment, "status"):
                qs = qs.exclude(status=cancelled_val)

            if qs.exists():
                raise ValidationError(_("This time is already allocated for this doctor."))

        return cleaned