# appointments/models.py
from __future__ import annotations

from datetime import date, timedelta

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models, transaction
from django.db.models import Q, Max
from django.utils import timezone
from django.utils.timezone import get_default_timezone, make_aware, make_naive
from django.utils.translation import gettext_lazy as _

from core.models import SoftDeleteModel  # ✅ Soft Delete base
from doctor.models import Doctor
from patient.models import Patient

# ------------------------------------------------------------------#
#                           Settings / Utils                         #
# ------------------------------------------------------------------#
LOCAL_TZ = get_default_timezone()


def _safe_int_setting(name: str, default: int, minimum: int = 0) -> int:
    """
    Read integer setting safely.
    - Allows 0
    - Applies minimum clamp
    """
    val = getattr(settings, name, default)
    try:
        val_int = int(val)
    except Exception:
        val_int = default
    return max(minimum, val_int)


# ✅ Past margin/tolerance (used for "now()" micro-flakes)
PAST_MARGIN_MIN = _safe_int_setting("APPOINTMENT_PAST_MARGIN_MINUTES", default=1, minimum=0)
PAST_MARGIN = timedelta(minutes=PAST_MARGIN_MIN)

# Always allow at least 60 seconds tolerance to prevent "now()" becoming "past" during validation.
PAST_TOLERANCE = max(PAST_MARGIN, timedelta(seconds=60))

# Gap minutes between appointments for same doctor
APPOINTMENT_GAP_MIN = _safe_int_setting("APPOINTMENT_GAP_MINUTES", default=1, minimum=0)

# If True: PatientBookingRequest will reject times that are already booked.
# If False: allow requests even if the slot is already taken (secretary decides later).
BOOKING_REQUEST_BLOCK_CONFLICTS = getattr(settings, "BOOKING_REQUEST_BLOCK_CONFLICTS", True)

# ✅ IMPORTANT:
# Tests عادة تتوقع منع أي وقت "بالماضي" حتى لو نفس اليوم.
# إذا تحتاج سلوك مختلف داخلياً تقدر تفعّله من settings صراحةً.
ALLOW_SAME_DAY_PAST_APPOINTMENTS = getattr(settings, "ALLOW_SAME_DAY_PAST_APPOINTMENTS", False)


def _use_tz() -> bool:
    return bool(getattr(settings, "USE_TZ", False))


def _now_local():
    """
    Return "now" normalized to project's local timezone.
    - If USE_TZ=True  -> aware in LOCAL_TZ
    - If USE_TZ=False -> naive (assumed local wall-clock)
    """
    now = timezone.now()

    if _use_tz():
        if timezone.is_naive(now):
            now = make_aware(now, LOCAL_TZ)
        return timezone.localtime(now, LOCAL_TZ)

    # USE_TZ False -> should be naive; if not, make it naive local
    if timezone.is_aware(now):
        now = timezone.localtime(now, LOCAL_TZ)
        now = make_naive(now, LOCAL_TZ)
    return now


def _normalize_dt(dt):
    """
    Normalize datetimes consistently for storage/validation.
    - None  -> None
    - If USE_TZ=True:
        * naive -> make_aware(..., LOCAL_TZ) (keeps wall clock)
        * aware -> convert to LOCAL_TZ
      returns aware
    - If USE_TZ=False:
        * aware -> convert to LOCAL_TZ then make_naive
        * naive -> keep as-is (assumed local)
      returns naive
    """
    if dt is None:
        return None

    if _use_tz():
        if timezone.is_naive(dt):
            return make_aware(dt, LOCAL_TZ)
        return timezone.localtime(dt, LOCAL_TZ)

    # USE_TZ False
    if timezone.is_aware(dt):
        dt_local = timezone.localtime(dt, LOCAL_TZ)
        return make_naive(dt_local, LOCAL_TZ)
    return dt


def _local_date_from_dt(dt) -> date | None:
    """Extract local calendar day from dt (aware/naive depending on USE_TZ)."""
    if dt is None:
        return None
    if _use_tz() and timezone.is_aware(dt):
        return timezone.localtime(dt, LOCAL_TZ).date()
    return dt.date()  # naive local


def _active_appointments_qs():
    """
    Base queryset for ACTIVE (non-soft-deleted) appointments.
    Works whether SoftDeleteModel uses a filtered manager or not.
    """
    qs = Appointment.objects.all()
    try:
        return qs.filter(is_deleted=False)
    except Exception:
        return qs


# ------------------------------------------------------------------#
#                            Choice enums                            #
# ------------------------------------------------------------------#
class AppointmentStatus(models.TextChoices):
    PENDING = "pending", _("Pending")
    CONFIRMED = "confirmed", _("Confirmed")
    CALLED = "called", _("Called")
    COMPLETED = "completed", _("Completed")
    CANCELLED = "cancelled", _("Cancelled")


class BookingRequestStatus(models.TextChoices):
    PENDING = "pending", _("Pending")
    REQUESTED = "requested", _("Requested")
    CONFIRMED = "confirmed", _("Confirmed")
    REJECTED = "rejected", _("Rejected")


# ------------------------------------------------------------------#
#                              Appointment                           #
# ------------------------------------------------------------------#
class Appointment(SoftDeleteModel):
    """Pure scheduling record – no clinical data."""

    patient = models.ForeignKey(
        Patient,
        on_delete=models.CASCADE,
        related_name="appointments",
    )
    doctor = models.ForeignKey(
        Doctor,
        on_delete=models.CASCADE,
        related_name="appointments",
        db_index=True,
    )

    scheduled_time = models.DateTimeField(null=True, blank=True, db_index=True)

    # Denormalized local calendar day derived from scheduled_time
    scheduled_day = models.DateField(
        null=True,
        blank=True,
        editable=False,
        db_index=True,
    )

    queue_number = models.PositiveIntegerField(
        null=True,
        blank=True,
        validators=[MinValueValidator(1)],
        help_text=_("Auto-generated per doctor per day."),
    )

    iqd_amount = models.DecimalField(
        max_digits=15,
        decimal_places=0,
        default=0,
        validators=[MinValueValidator(0)],
    )

    notes = models.TextField(blank=True, null=True)

    status = models.CharField(
        max_length=20,
        choices=AppointmentStatus.choices,
        default=AppointmentStatus.PENDING,
        db_index=True,
    )

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["scheduled_time", "pk"]
        constraints = [
            # ✅ Prevent double-booking doctor+time for ACTIVE appointments (not cancelled) AND not soft-deleted
            models.UniqueConstraint(
                fields=["doctor", "scheduled_time"],
                name="uq_doctor_time_not_cancelled",
                condition=(
                    Q(scheduled_time__isnull=False)
                    & Q(is_deleted=False)
                    & ~Q(status=AppointmentStatus.CANCELLED)
                ),
            ),
            # ✅ Unique queue per doctor+day for ACTIVE appointments (not cancelled) AND not soft-deleted
            models.UniqueConstraint(
                fields=["doctor", "scheduled_day", "queue_number"],
                name="uq_doctor_day_queue_active",
                condition=(
                    Q(scheduled_day__isnull=False)
                    & Q(queue_number__isnull=False)
                    & Q(is_deleted=False)
                    & ~Q(status=AppointmentStatus.CANCELLED)
                ),
            ),
        ]
        indexes = [
            models.Index(fields=["doctor", "scheduled_day", "status"], name="idx_doc_day_status"),
        ]

    def clean(self):
        super().clean()

        if not self.scheduled_time or not self.doctor_id:
            return

        norm_dt = _normalize_dt(self.scheduled_time)
        self.scheduled_time = norm_dt
        self.scheduled_day = _local_date_from_dt(norm_dt)

        time_changed = True
        doctor_changed = True
        if self.pk:
            old = Appointment.objects.filter(pk=self.pk).only("scheduled_time", "doctor_id").first()
            if old:
                old_time = _normalize_dt(old.scheduled_time) if old.scheduled_time else None
                time_changed = (old_time != norm_dt)
                doctor_changed = (old.doctor_id != self.doctor_id)

        # ✅ If cancelled: skip collision/gap rules
        if self.status == AppointmentStatus.CANCELLED:
            return

        # ✅ Past validation only when create or change time/doctor
        if (self.pk is None) or time_changed or doctor_changed:
            now_local = _now_local()
            if norm_dt < (now_local - PAST_TOLERANCE):
                if not (
                    ALLOW_SAME_DAY_PAST_APPOINTMENTS
                    and self.scheduled_day is not None
                    and self.scheduled_day == now_local.date()
                ):
                    raise ValidationError({"scheduled_time": _("Cannot set an appointment time in the past.")})

        # ✅ ACTIVE collision check (exact time)
        clash_exact = (
            _active_appointments_qs()
            .exclude(pk=self.pk)
            .filter(doctor_id=self.doctor_id, scheduled_time=norm_dt)
            .exclude(status=AppointmentStatus.CANCELLED)
            .exists()
        )
        if clash_exact:
            raise ValidationError({"scheduled_time": _("This time slot is already booked for this doctor.")})

        # Gap rule
        if APPOINTMENT_GAP_MIN > 0 and ((self.pk is None) or time_changed or doctor_changed):
            gap = timedelta(minutes=APPOINTMENT_GAP_MIN)
            window_start = norm_dt - gap
            window_end = norm_dt + gap

            overlap = (
                _active_appointments_qs()
                .exclude(pk=self.pk)
                .filter(doctor_id=self.doctor_id)
                .exclude(status=AppointmentStatus.CANCELLED)
                .filter(scheduled_time__gt=window_start, scheduled_time__lt=window_end)
                .exists()
            )
            if overlap:
                raise ValidationError(
                    {"scheduled_time": _("A minimum gap is required between appointments for the same doctor.")}
                )

    def _compute_next_queue_number(self) -> int:
        if not self.doctor_id or not self.scheduled_day:
            return 1

        qs = (
            _active_appointments_qs()
            .filter(doctor_id=self.doctor_id, scheduled_day=self.scheduled_day)
            .exclude(status=AppointmentStatus.CANCELLED)
            .filter(queue_number__isnull=False)
        )
        if self.pk:
            qs = qs.exclude(pk=self.pk)

        last = qs.aggregate(mx=Max("queue_number"))["mx"] or 0
        return int(last) + 1

    def save(self, *args, **kwargs):
        update_fields = kwargs.get("update_fields")
        if update_fields is not None:
            uf = set(update_fields)
            soft_fields = {"is_deleted", "deleted_at", "deleted_by"}
            if uf.issubset(soft_fields):
                return super().save(*args, **kwargs)

        self.scheduled_time = _normalize_dt(self.scheduled_time)
        self.scheduled_day = _local_date_from_dt(self.scheduled_time)

        if self.iqd_amount is None:
            self.iqd_amount = 0

        creating = self.pk is None

        if self.status == AppointmentStatus.CANCELLED:
            self.queue_number = None

        if not creating:
            old = (
                Appointment.objects.filter(pk=self.pk)
                .only("doctor_id", "scheduled_day", "status", "queue_number")
                .first()
            )

            doctor_or_day_changed = bool(
                old and (old.doctor_id != self.doctor_id or old.scheduled_day != self.scheduled_day)
            )
            became_active = bool(
                old and old.status == AppointmentStatus.CANCELLED and self.status != AppointmentStatus.CANCELLED
            )

            needs_queue = bool(
                self.scheduled_time
                and self.status != AppointmentStatus.CANCELLED
                and (doctor_or_day_changed or became_active or (self.queue_number is None))
            )

            if needs_queue:
                with transaction.atomic():
                    Doctor.objects.select_for_update().get(pk=self.doctor_id)
                    self.queue_number = self._compute_next_queue_number()
                    self.full_clean()
                    return super().save(*args, **kwargs)

            self.full_clean()
            return super().save(*args, **kwargs)

        if not self.scheduled_time or self.status == AppointmentStatus.CANCELLED:
            self.full_clean()
            return super().save(*args, **kwargs)

        with transaction.atomic():
            Doctor.objects.select_for_update().get(pk=self.doctor_id)
            self.queue_number = self._compute_next_queue_number()
            self.full_clean()
            return super().save(*args, **kwargs)

    def restore(self):
        self.is_deleted = False
        self.deleted_at = None
        self.deleted_by = None
        self.save()

    def __str__(self):
        pat = getattr(self.patient, "full_name", str(self.patient))
        doc_user = getattr(self.doctor, "user", None)
        doc = (
            (doc_user.get_full_name() if doc_user else "")
            or (doc_user.username if doc_user else "")
            or "Doctor"
        )
        q = f"#{self.queue_number}" if self.queue_number else "—"
        try:
            amt = f"{int(self.iqd_amount):,} IQD" if self.iqd_amount is not None else "0 IQD"
        except Exception:
            amt = "0 IQD"
        return f"{pat} → Dr. {doc} ({q}) | {amt}"


# ------------------------------------------------------------------#
#                        Patient booking request                      #
# ------------------------------------------------------------------#
class PatientBookingRequest(SoftDeleteModel):
    """
    External / portal booking requests.

    ✅ Now SoftDeleteModel:
    - any delete in admin becomes soft-delete by default
    - supports restore()
    """

    full_name = models.CharField(max_length=100)
    date_of_birth = models.DateField(blank=True, null=True)
    contact_info = models.CharField(max_length=200)

    doctor = models.ForeignKey(
        Doctor,
        on_delete=models.CASCADE,
        related_name="booking_requests",
    )
    scheduled_time = models.DateTimeField(db_index=True)
    submitted_at = models.DateTimeField(auto_now_add=True, db_index=True)

    status = models.CharField(
        max_length=20,
        choices=BookingRequestStatus.choices,
        default=BookingRequestStatus.REQUESTED,
        db_index=True,
    )

    patient = models.ForeignKey(
        Patient,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="booking_requests",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="booking_requests",
    )

    # ✅ idempotent approve: link request to created appointment
    appointment = models.OneToOneField(
        "Appointment",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="origin_booking_request",
    )

    seen_by_secretary = models.BooleanField(
        default=False,
        db_index=True,
        help_text=_("Marked as True once a secretary has viewed this request."),
    )
    seen_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name=_("Seen at"),
    )

    class Meta:
        ordering = ["-submitted_at", "pk"]
        indexes = [
            models.Index(fields=["doctor", "status", "seen_by_secretary"], name="idx_br_doc_status_seen"),
        ]

    def clean(self):
        super().clean()

        errors = {}
        if not self.scheduled_time or not self.doctor_id:
            return

        norm_dt = _normalize_dt(self.scheduled_time)
        self.scheduled_time = norm_dt

        time_changed = True
        doctor_changed = True
        if self.pk:
            old = PatientBookingRequest.objects.filter(pk=self.pk).only("scheduled_time", "doctor_id").first()
            if old:
                old_time = _normalize_dt(old.scheduled_time) if old.scheduled_time else None
                time_changed = (old_time != norm_dt)
                doctor_changed = (old.doctor_id != self.doctor_id)

        if (self.pk is None) or time_changed or doctor_changed:
            if norm_dt < (_now_local() - PAST_TOLERANCE):
                errors["scheduled_time"] = _("Requested time is in the past.")

        if (
            BOOKING_REQUEST_BLOCK_CONFLICTS
            and self.doctor_id
            and self.scheduled_time
            and ((self.pk is None) or time_changed or doctor_changed)
        ):
            if (
                _active_appointments_qs()
                .filter(doctor_id=self.doctor_id, scheduled_time=norm_dt)
                .exclude(status=AppointmentStatus.CANCELLED)
                .exists()
            ):
                errors["scheduled_time"] = _("This time is already allocated for this doctor.")

        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        creating = self.pk is None
        self.scheduled_time = _normalize_dt(self.scheduled_time)
        self.full_clean()
        super().save(*args, **kwargs)

        if creating:
            try:
                doc_user = getattr(self.doctor, "user", None)
                doc_name = (
                    (doc_user.get_full_name() if doc_user else "")
                    or (doc_user.username if doc_user else "")
                    or "Doctor"
                )

                Notification.objects.create(
                    title=_("New Patient Booking"),
                    message=(
                        f"{self.full_name} requested an appointment with Dr. {doc_name} on "
                        f"{self.scheduled_time:%Y-%m-%d %I:%M %p}."
                    ),
                    related_booking_request=self,
                )
            except Exception:
                pass

    def __str__(self):
        doc_user = getattr(self.doctor, "user", None)
        doc = (doc_user.get_full_name() if doc_user else "") or (doc_user.username if doc_user else "") or "Doctor"
        return f"{self.full_name} → Dr. {doc} @ {self.scheduled_time:%Y-%m-%d %H:%M} ({self.status})"


# ------------------------------------------------------------------#
#                               Notification                         #
# ------------------------------------------------------------------#
class Notification(SoftDeleteModel):
    """
    Simple notification model used by the secretary bell + list view.

    ✅ Now SoftDeleteModel:
    - Admin delete / delete selected becomes soft-delete by default
    - supports restore()
    """

    title = models.CharField(max_length=200)
    message = models.TextField()
    is_read = models.BooleanField(default=False, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    related_booking_request = models.ForeignKey(
        "PatientBookingRequest",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="notifications",
    )

    class Meta:
        ordering = ["-created_at", "pk"]

    def __str__(self):
        state = _("Read") if self.is_read else _("Unread")
        return f"{self.title} — {state}"