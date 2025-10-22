# appointments/forms.py

from __future__ import annotations

from datetime import timedelta

from django import forms
from django.core.exceptions import ValidationError
from django.utils import timezone
from django.utils.timezone import get_default_timezone, make_aware, localtime
from django.utils.translation import gettext_lazy as _

from .models import (
    Appointment,
    PatientBookingRequest,
    AppointmentStatus,
    PAST_MARGIN,   # نستخدم نفس الهامش المعرّف في الموديل
)
from patient.models import Patient
from doctor.models import Doctor


# =============================
# Helpers / Widgets
# =============================
_LOCAL_TZ = get_default_timezone()

def _to_local_aware(dt):
    """حوّل datetime إلى Aware على المنطقة المحلية بدون تغيير ساعة العرض."""
    if dt is None:
        return None
    if timezone.is_naive(dt):
        return make_aware(dt, _LOCAL_TZ)
    return dt.astimezone(_LOCAL_TZ)


class DateTimeLocalInput(forms.DateTimeInput):
    input_type = "datetime-local"
    format = "%Y-%m-%dT%H:%M"

    def __init__(self, **kwargs):
        attrs = kwargs.pop("attrs", {})
        base = {"class": "form-control"}
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


# =============================
# Appointment Form (staff)
# =============================
class AppointmentForm(forms.ModelForm):
    """
    نموذج إنشاء/تعديل موعد داخليًا.
    - يمنع الحجز في الماضي (مع هامش PAST_MARGIN)
    - يفرض فجوة دقيقة واحدة حول الموعد لنفس الطبيب
    """

    scheduled_time = forms.DateTimeField(
        widget=DateTimeLocalInput(),
        input_formats=[DateTimeLocalInput.format],
        label=_("Appointment Time"),
        help_text=_("Pick a future time (YYYY-MM-DD HH:MM)."),
    )

    status = forms.ChoiceField(
        choices=AppointmentStatus.choices,
        widget=forms.Select(attrs={"class": "form-select"}),
        label=_("Status"),
    )

    iqd_amount = forms.DecimalField(
        max_digits=15,
        decimal_places=0,
        min_value=0,
        required=False,
        label=_("Amount (IQD)"),
        widget=forms.NumberInput(
            attrs={"class": "form-control", "placeholder": _("Amount in IQD")}
        ),
        help_text=_("Optional. Defaults to 0 if left blank."),
    )

    notes = forms.CharField(
        required=False,
        label=_("Notes"),
        widget=forms.Textarea(
            attrs={"class": "form-control", "rows": 2, "placeholder": _("Optional notes")}
        ),
    )

    class Meta:
        model = Appointment
        fields = ["patient", "doctor", "scheduled_time", "status", "iqd_amount", "notes"]
        widgets = {
            "patient": forms.Select(attrs={"class": "form-select"}),
            "doctor": forms.Select(attrs={"class": "form-select"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # ترتيب القوائم وتسميات واضحة
        self.fields["patient"].queryset = Patient.objects.order_by("full_name")
        self.fields["doctor"].queryset = (
            Doctor.objects.select_related("user").order_by("user__first_name", "user__last_name")
        )
        self.fields["doctor"].label_from_instance = lambda obj: (
            getattr(obj, "full_name", None) or obj.user.get_full_name() or obj.user.username
        )

        # حفظ القيمة الحالية للمبلغ عند التحرير
        if self.instance.pk and self.instance.iqd_amount is not None:
            self.initial["iqd_amount"] = self.instance.iqd_amount

    def clean_scheduled_time(self):
        dt = self.cleaned_data.get("scheduled_time")
        if not dt:
            return dt

        aware = _to_local_aware(dt)
        # اسمح بالهامش كما في الموديل
        if aware < localtime() - PAST_MARGIN:
            raise ValidationError(_("The selected time is in the past."))

        return aware  # نُرجع aware لتستخدمه بقية عمليات التنظيف

    def clean(self):
        cleaned = super().clean()
        doctor = cleaned.get("doctor")
        scheduled_time = cleaned.get("scheduled_time")

        # إذا clean_scheduled_time أعادت naive (في حالات نادرة)، نضمن التحويل هنا
        scheduled_time = _to_local_aware(scheduled_time) if scheduled_time else None

        if doctor and scheduled_time:
            # فرض فجوة دقيقة قبل/بعد الموعد لنفس الطبيب
            window_start = scheduled_time - timedelta(minutes=1)
            window_end = scheduled_time + timedelta(minutes=1)

            overlapping = (
                Appointment.objects.filter(
                    doctor=doctor, scheduled_time__range=(window_start, window_end)
                )
                .exclude(pk=self.instance.pk)
                .exists()
            )
            if overlapping:
                raise ValidationError(
                    _("At least a one-minute gap is required between appointments for the same doctor.")
                )

        # افتراضيًا صفر إن ترك الحقل فارغًا
        if cleaned.get("iqd_amount") in (None, ""):
            cleaned["iqd_amount"] = 0

        return cleaned


# =============================
# Public Booking Form
# =============================
class PatientBookingForm(forms.ModelForm):
    """نموذج حجز عام (للزوار)."""

    full_name = forms.CharField(
        max_length=100,
        label=_("Your Full Name"),
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": _("Enter your full name")}),
    )

    contact_info = forms.CharField(
        max_length=200,  # يطابق الموديل (كان 50 في النموذج)
        label=_("Phone / Contact"),
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": _("Your phone number")}),
        help_text=_("We will use this to contact you."),
    )

    date_of_birth = forms.DateField(
        required=False,  # اختياري ليتوافق مع الموديل
        label=_("Your Date of Birth"),
        widget=DateInput(),
        input_formats=[DateInput.format],
    )

    scheduled_time = forms.DateTimeField(
        widget=DateTimeLocalInput(),
        input_formats=[DateTimeLocalInput.format],
        label=_("Preferred Time"),
        help_text=_("Pick a future time (YYYY-MM-DD HH:MM)."),
    )

    class Meta:
        model = PatientBookingRequest
        fields = ["full_name", "date_of_birth", "contact_info", "doctor", "scheduled_time"]
        widgets = {"doctor": forms.Select(attrs={"class": "form-select"})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["doctor"].queryset = (
            Doctor.objects.select_related("user").order_by("user__first_name", "user__last_name")
        )
        self.fields["doctor"].label_from_instance = lambda obj: (
            getattr(obj, "full_name", None) or obj.user.get_full_name() or obj.user.username
        )

    def clean_scheduled_time(self):
        dt = self.cleaned_data.get("scheduled_time")
        if not dt:
            return dt
        aware = _to_local_aware(dt)
        if aware < localtime() - PAST_MARGIN:
            raise ValidationError(_("Please choose a future time."))
        return aware

    def clean(self):
        cleaned = super().clean()
        doctor = cleaned.get("doctor")
        scheduled_time = cleaned.get("scheduled_time")
        scheduled_time = _to_local_aware(scheduled_time) if scheduled_time else None

        # فحص التعارض مبكرًا لإظهار رسالة ودّية (الموديل سيتحقق أيضًا)
        if doctor and scheduled_time:
            exists = Appointment.objects.filter(
                doctor_id=doctor.id, scheduled_time=scheduled_time
            ).exists()
            if exists:
                raise ValidationError(_("This time is already allocated for this doctor."))
        return cleaned
