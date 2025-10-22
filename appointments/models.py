# appointments/models.py
#
# 31-Jul-2025 – Local‑TZ aware + race‑safe queue + cancelled‑slot rebookable
# Updated (compat): remove UniqueConstraint(expressions=...) usage, add denormalized
# `scheduled_day` to support doctor×day×queue uniqueness on all Django versions.
# ------------------------------------------------------------------
# • Converts any naïve datetime to timezone‑aware using settings.TIME_ZONE.
# • Allows booking "now" with a small margin (PAST_MARGIN).
# • Deterministic queue numbering per (doctor, local day), race‑safe via SELECT ... FOR UPDATE.
# • Active‑only uniqueness (excludes CANCELLED) for both time and queue.
# • Cancelled appointments don’t block re‑booking the same time/queue.
# ------------------------------------------------------------------

from __future__ import annotations

from datetime import timedelta

from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models, transaction
from django.db.models import Q, Max
from django.utils import timezone
from django.utils.timezone import get_default_timezone, localtime, make_aware
from django.utils.translation import gettext_lazy as _

from doctor.models import Doctor
from patient.models import Patient


# ------------------------------------------------------------------#
#                           Settings / Utils                         #
# ------------------------------------------------------------------#
LOCAL_TZ = get_default_timezone()
PAST_MARGIN = timedelta(minutes=1)


def _to_local_aware(dt):
    """Normalize datetimes to be timezone‑aware in the project's local TZ.
    - None -> None
    - naïve -> make_aware(..., LOCAL_TZ)
    - aware -> convert to LOCAL_TZ
    """
    if dt is None:
        return None
    if timezone.is_naive(dt):
        return make_aware(dt, LOCAL_TZ)
    return dt.astimezone(LOCAL_TZ)


# ------------------------------------------------------------------#
#                            Choice enums                            #
# ------------------------------------------------------------------#
class AppointmentStatus(models.TextChoices):
    PENDING = "pending", _("Pending")
    COMPLETED = "completed", _("Completed")
    CANCELLED = "cancelled", _("Cancelled")


class BookingRequestStatus(models.TextChoices):
    PENDING = "pending", _("Pending")
    CONFIRMED = "confirmed", _("Confirmed")
    REJECTED = "rejected", _("Rejected")


# ------------------------------------------------------------------#
#                              Appointment                           #
# ------------------------------------------------------------------#
class Appointment(models.Model):
    """Pure scheduling record – no clinical data."""

    patient = models.ForeignKey(
        Patient, on_delete=models.CASCADE, related_name="appointments"
    )
    doctor = models.ForeignKey(
        Doctor, on_delete=models.CASCADE, related_name="appointments", db_index=True
    )

    # Wall clock in local TZ (stored UTC by Django; normalized via _to_local_aware)
    scheduled_time = models.DateTimeField(null=True, blank=True, db_index=True)

    # Denormalized local calendar day derived from scheduled_time
    scheduled_day = models.DateField(null=True, blank=True, editable=False, db_index=True)

    queue_number = models.PositiveIntegerField(null=True, blank=True)
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
            # Prevent double‑booking the exact same timestamp for the same doctor
            # (does NOT consider CANCELLED as conflicting; allows re‑booking)
            models.UniqueConstraint(
                fields=["doctor", "scheduled_time"],
                name="uq_doctor_time_not_cancelled",
                condition=Q(scheduled_time__isnull=False)
                & ~Q(status=AppointmentStatus.CANCELLED),
            ),
            # Ensure unique queue_number per (doctor × local scheduled_day) for active appts
            models.UniqueConstraint(
                fields=["doctor", "scheduled_day", "queue_number"],
                name="uq_doctor_day_queue_active",
                condition=Q(scheduled_day__isnull=False)
                & Q(queue_number__isnull=False)
                & ~Q(status=AppointmentStatus.CANCELLED),
            ),
        ]
        indexes = [
            models.Index(fields=["doctor", "scheduled_day", "status"], name="idx_doc_day_status"),
        ]

    # ----------------------------- Clean ---------------------------#
    def clean(self):
        # If there is no scheduled_time yet, nothing to validate here
        if not self.scheduled_time:
            return

        aware = _to_local_aware(self.scheduled_time)

        # Disallow booking strictly in the past (with a small grace margin)
        if aware < localtime() - PAST_MARGIN:
            raise ValidationError(
                {"scheduled_time": _("Cannot book an appointment in the past.")}
            )

        # Prevent same doctor@time clash for active appointments
        clash = (
            Appointment.objects.exclude(pk=self.pk)
            .filter(
                doctor_id=self.doctor_id,
                scheduled_time=aware,
            )
            .exclude(status=AppointmentStatus.CANCELLED)
            .exists()
        )
        if clash:
            raise ValidationError(
                {"scheduled_time": _("This time slot is already booked for this doctor.")}
            )

    # ------------------------------ Save ---------------------------#
    def save(self, *args, **kwargs):
        """Guarantee local‑TZ normalization and race‑safe queue numbering.
        Logic:
        - Normalize scheduled_time to local‑aware; compute scheduled_day accordingly.
        - On updates: do not re‑number queues.
        - On creates with scheduled_time: lock Doctor row, compute next queue_number
          for (doctor, scheduled_day) among ACTIVE appts (non‑cancelled), validate,
          then save — all inside a single transaction.
        """
        # Normalize time and derive day (in local calendar)
        self.scheduled_time = _to_local_aware(self.scheduled_time)
        if self.scheduled_time:
            self.scheduled_day = self.scheduled_time.astimezone(LOCAL_TZ).date()
        else:
            self.scheduled_day = None

        if self.iqd_amount is None:
            self.iqd_amount = 0

        creating = self.pk is None

        # Updates: keep current queue_number; just validate and save
        if not creating:
            self.full_clean()
            return super().save(*args, **kwargs)

        # Creating without a scheduled_time: no queue numbering needed
        if not self.scheduled_time:
            self.full_clean()
            return super().save(*args, **kwargs)

        # Creating WITH a scheduled_time: compute queue number safely
        with transaction.atomic():
            # Serialize queue numbering per doctor by locking the doctor row
            Doctor.objects.select_for_update().get(pk=self.doctor_id)

            qs = (
                Appointment.objects.select_for_update()
                .filter(doctor_id=self.doctor_id, scheduled_day=self.scheduled_day)
                .exclude(status=AppointmentStatus.CANCELLED)
            )
            last = qs.aggregate(mx=Max("queue_number"))["mx"] or 0
            self.queue_number = last + 1

            self.full_clean()
            return super().save(*args, **kwargs)

    # ---------------------------- Dunder ---------------------------#
    def __str__(self):
        pat = getattr(self.patient, "full_name", str(self.patient))
        doc = self.doctor.user.get_full_name() or self.doctor.user.username
        q = f"#{self.queue_number}" if self.queue_number else "—"
        amt = f"{int(self.iqd_amount):,} IQD"
        return f"{pat} → Dr. {doc} ({q}) | {amt}"


# ------------------------------------------------------------------#
#                        Patient booking request                     #
# ------------------------------------------------------------------#
class PatientBookingRequest(models.Model):
    full_name = models.CharField(max_length=100)
    date_of_birth = models.DateField(blank=True, null=True)
    contact_info = models.CharField(max_length=200)

    doctor = models.ForeignKey(
        Doctor, on_delete=models.CASCADE, related_name="booking_requests"
    )
    scheduled_time = models.DateTimeField(db_index=True)
    submitted_at = models.DateTimeField(auto_now_add=True, db_index=True)
    status = models.CharField(
        max_length=20,
        choices=BookingRequestStatus.choices,
        default=BookingRequestStatus.PENDING,
        db_index=True,
    )

    class Meta:
        ordering = ["-submitted_at", "pk"]

    # ----------------------------- Clean ---------------------------#
    def clean(self):
        errors = {}

        if self.scheduled_time:
            aware = _to_local_aware(self.scheduled_time)
            if aware < localtime() - PAST_MARGIN:
                errors["scheduled_time"] = _("Requested time is in the past.")

        if self.doctor_id and self.scheduled_time:
            # Reject if an active appointment already occupies this exact timestamp
            if (
                Appointment.objects.filter(
                    doctor_id=self.doctor_id,
                    scheduled_time=_to_local_aware(self.scheduled_time),
                )
                .exclude(status=AppointmentStatus.CANCELLED)
                .exists()
            ):
                errors["scheduled_time"] = _(
                    "This time is already allocated for this doctor."
                )

        if errors:
            raise ValidationError(errors)

    # ----------------------------- Save ----------------------------#
    def save(self, *args, **kwargs):
        creating = self.pk is None
        self.scheduled_time = _to_local_aware(self.scheduled_time)
        self.full_clean()
        super().save(*args, **kwargs)

        # Fire a simple notification on create (best‑effort, after persistence)
        if creating:
            Notification.objects.create(
                title=_("New Patient Booking"),
                message=(
                    f"{self.full_name} requested an appointment with "
                    f"Dr. {self.doctor.user.get_full_name()} on "
                    f"{self.scheduled_time:%Y-%m-%d %I:%M %p}."
                ),
                related_booking_request=self,
            )

    def __str__(self):
        return (
            f"{self.full_name} → Dr. {self.doctor.user.get_full_name()} "
            f"@ {self.scheduled_time:%Y-%m-%d %H:%M} ({self.status})"
        )


# ------------------------------------------------------------------#
#                               Notification                        #
# ------------------------------------------------------------------#
class Notification(models.Model):
    title = models.CharField(max_length=200)
    message = models.TextField()
    is_read = models.BooleanField(default=False, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    related_booking_request = models.ForeignKey(
        PatientBookingRequest,
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
