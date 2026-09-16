from __future__ import annotations

from datetime import timedelta

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models, transaction
from django.db.models import Max, Q
from django.utils import timezone
from django.utils.timezone import (
    get_default_timezone,
    make_aware,
)
from django.utils.translation import gettext_lazy as _

from core.models import SoftDeleteModel
from doctor.models import Doctor
from hospital.models import (
    Branch,
    Department,
    Hospital,
    StaffAssignment,
)
from patient.models import Patient


LOCAL_TZ = get_default_timezone()


def _safe_int_setting(
    name: str,
    default: int,
    minimum: int = 0,
) -> int:
    value = getattr(settings, name, default)

    try:
        value_int = int(value)
    except (TypeError, ValueError):
        value_int = default

    return max(minimum, value_int)


PAST_MARGIN_MIN = _safe_int_setting(
    "APPOINTMENT_PAST_MARGIN_MINUTES",
    default=1,
    minimum=0,
)

PAST_MARGIN = timedelta(minutes=PAST_MARGIN_MIN)

APPOINTMENT_GAP_MIN = _safe_int_setting(
    "APPOINTMENT_GAP_MINUTES",
    default=1,
    minimum=0,
)

BOOKING_REQUEST_BLOCK_CONFLICTS = getattr(
    settings,
    "BOOKING_REQUEST_BLOCK_CONFLICTS",
    True,
)


def _now_local():
    now = timezone.now()

    if timezone.is_naive(now):
        return make_aware(now, LOCAL_TZ)

    return timezone.localtime(now, LOCAL_TZ)


def _to_local_aware(value):
    if value is None:
        return None

    if timezone.is_naive(value):
        return make_aware(value, LOCAL_TZ)

    return timezone.localtime(value, LOCAL_TZ)


def _get_doctor_user_id(doctor_id):
    if not doctor_id:
        return None

    return (
        Doctor.objects.filter(pk=doctor_id)
        .values_list("user_id", flat=True)
        .first()
    )


def _get_primary_doctor_assignment(doctor_id):
    user_id = _get_doctor_user_id(doctor_id)

    if not user_id:
        return None

    return (
        StaffAssignment.objects.select_related(
            "hospital",
            "branch",
            "department",
        )
        .filter(
            user_id=user_id,
            role=StaffAssignment.Roles.DOCTOR,
            is_active=True,
        )
        .order_by("-is_primary", "pk")
        .first()
    )


def _populate_location(instance):
    if instance.department_id and not instance.branch_id:
        department_branch_id = (
            Department.objects.filter(pk=instance.department_id)
            .values_list("branch_id", flat=True)
            .first()
        )

        if department_branch_id:
            instance.branch_id = department_branch_id

    if instance.branch_id and not instance.hospital_id:
        branch_hospital_id = (
            Branch.objects.filter(pk=instance.branch_id)
            .values_list("hospital_id", flat=True)
            .first()
        )

        if branch_hospital_id:
            instance.hospital_id = branch_hospital_id

    assignment = _get_primary_doctor_assignment(
        instance.doctor_id
    )

    if not assignment:
        return

    if not instance.hospital_id:
        instance.hospital_id = assignment.hospital_id

    if (
        not instance.branch_id
        and assignment.branch_id
        and assignment.hospital_id == instance.hospital_id
    ):
        instance.branch_id = assignment.branch_id

    if (
        not instance.department_id
        and assignment.department_id
        and assignment.branch_id == instance.branch_id
    ):
        instance.department_id = assignment.department_id


def _get_location_validation_errors(instance):
    errors = {}

    if instance.branch_id and instance.hospital_id:
        branch_hospital_id = (
            Branch.objects.filter(pk=instance.branch_id)
            .values_list("hospital_id", flat=True)
            .first()
        )

        if (
            branch_hospital_id
            and branch_hospital_id != instance.hospital_id
        ):
            errors["branch"] = (
                "The selected branch does not belong "
                "to the selected hospital."
            )

    if instance.department_id:
        department_branch_id = (
            Department.objects.filter(pk=instance.department_id)
            .values_list("branch_id", flat=True)
            .first()
        )

        if not instance.branch_id:
            errors["branch"] = (
                "A branch is required when a department "
                "is selected."
            )
        elif (
            department_branch_id
            and department_branch_id != instance.branch_id
        ):
            errors["department"] = (
                "The selected department does not belong "
                "to the selected branch."
            )

    if instance.doctor_id and instance.hospital_id:
        user_id = _get_doctor_user_id(instance.doctor_id)

        if user_id:
            assignments = StaffAssignment.objects.filter(
                user_id=user_id,
                role=StaffAssignment.Roles.DOCTOR,
                hospital_id=instance.hospital_id,
                is_active=True,
            )

            if instance.branch_id:
                assignments = assignments.filter(
                    branch_id=instance.branch_id
                )

            if instance.department_id:
                assignments = assignments.filter(
                    department_id=instance.department_id
                )

            if not assignments.exists():
                errors["doctor"] = (
                    "This doctor does not have an active "
                    "assignment at the selected location."
                )

    return errors


class AppointmentStatus(models.TextChoices):
    PENDING = "pending", _("Pending")
    COMPLETED = "completed", _("Completed")
    CANCELLED = "cancelled", _("Cancelled")


class BookingRequestStatus(models.TextChoices):
    PENDING = "pending", _("Pending")
    REQUESTED = "requested", _("Requested")
    CONFIRMED = "confirmed", _("Confirmed")
    REJECTED = "rejected", _("Rejected")


class Appointment(SoftDeleteModel):
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

    hospital = models.ForeignKey(
        Hospital,
        on_delete=models.PROTECT,
        related_name="appointments",
        null=True,
        blank=True,
    )

    branch = models.ForeignKey(
        Branch,
        on_delete=models.PROTECT,
        related_name="appointments",
        null=True,
        blank=True,
    )

    department = models.ForeignKey(
        Department,
        on_delete=models.PROTECT,
        related_name="appointments",
        null=True,
        blank=True,
    )

    scheduled_time = models.DateTimeField(
        null=True,
        blank=True,
        db_index=True,
    )

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

    notes = models.TextField(
        blank=True,
        null=True,
    )

    status = models.CharField(
        max_length=20,
        choices=AppointmentStatus.choices,
        default=AppointmentStatus.PENDING,
        db_index=True,
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
        db_index=True,
    )

    class Meta:
        ordering = ["scheduled_time", "pk"]

        constraints = [
            models.UniqueConstraint(
                fields=["doctor", "scheduled_time"],
                name="uq_doctor_time_not_cancelled",
                condition=(
                    Q(scheduled_time__isnull=False)
                    & Q(is_deleted=False)
                    & ~Q(status=AppointmentStatus.CANCELLED)
                ),
            ),
            models.UniqueConstraint(
                fields=[
                    "doctor",
                    "scheduled_day",
                    "queue_number",
                ],
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
            models.Index(
                fields=[
                    "doctor",
                    "scheduled_day",
                    "status",
                ],
                name="idx_doc_day_status",
            ),
            models.Index(
                fields=[
                    "hospital",
                    "branch",
                    "scheduled_day",
                ],
                name="idx_appt_hosp_branch_day",
            ),
            models.Index(
                fields=[
                    "department",
                    "scheduled_day",
                    "status",
                ],
                name="idx_appt_dept_day_status",
            ),
        ]

    def clean(self):
        super().clean()

        location_errors = _get_location_validation_errors(self)

        if location_errors:
            raise ValidationError(location_errors)

        if not self.scheduled_time:
            return

        if not self.doctor_id:
            return

        aware = _to_local_aware(self.scheduled_time)
        self.scheduled_time = aware

        time_changed = True
        doctor_changed = True

        if self.pk:
            old = (
                Appointment.objects.filter(pk=self.pk)
                .only("scheduled_time", "doctor_id")
                .first()
            )

            if old:
                old_time = (
                    _to_local_aware(old.scheduled_time)
                    if old.scheduled_time
                    else None
                )

                time_changed = old_time != aware
                doctor_changed = (
                    old.doctor_id != self.doctor_id
                )

        if (
            self.pk is None
            or time_changed
            or doctor_changed
        ):
            if aware < _now_local() - PAST_MARGIN:
                raise ValidationError(
                    {
                        "scheduled_time": _(
                            "Cannot set an appointment "
                            "time in the past."
                        )
                    }
                )

        if self.status == AppointmentStatus.CANCELLED:
            return

        clash_exact = (
            Appointment.objects.exclude(pk=self.pk)
            .filter(
                doctor_id=self.doctor_id,
                scheduled_time=aware,
            )
            .exclude(status=AppointmentStatus.CANCELLED)
            .exists()
        )

        if clash_exact:
            raise ValidationError(
                {
                    "scheduled_time": _(
                        "This time slot is already booked "
                        "for this doctor."
                    )
                }
            )

        if (
            APPOINTMENT_GAP_MIN > 0
            and (
                self.pk is None
                or time_changed
                or doctor_changed
            )
        ):
            gap = timedelta(
                minutes=APPOINTMENT_GAP_MIN
            )

            window_start = aware - gap
            window_end = aware + gap

            overlap = (
                Appointment.objects.exclude(pk=self.pk)
                .filter(doctor_id=self.doctor_id)
                .exclude(status=AppointmentStatus.CANCELLED)
                .filter(
                    scheduled_time__gt=window_start,
                    scheduled_time__lt=window_end,
                )
                .exists()
            )

            if overlap:
                raise ValidationError(
                    {
                        "scheduled_time": _(
                            "A minimum gap is required "
                            "between appointments for "
                            "the same doctor."
                        )
                    }
                )

    def _compute_next_queue_number(self) -> int:
        appointments = (
            Appointment.objects.filter(
                doctor_id=self.doctor_id,
                scheduled_day=self.scheduled_day,
            )
            .exclude(status=AppointmentStatus.CANCELLED)
            .filter(queue_number__isnull=False)
        )

        if self.pk:
            appointments = appointments.exclude(pk=self.pk)

        last_number = (
            appointments.aggregate(
                maximum=Max("queue_number")
            )["maximum"]
            or 0
        )

        return int(last_number) + 1

    def save(self, *args, **kwargs):
        update_fields = kwargs.get("update_fields")

        if update_fields is not None:
            update_field_names = set(update_fields)

            soft_delete_fields = {
                "is_deleted",
                "deleted_at",
                "deleted_by",
            }

            if update_field_names.issubset(
                soft_delete_fields
            ):
                return super().save(*args, **kwargs)

        _populate_location(self)

        self.scheduled_time = _to_local_aware(
            self.scheduled_time
        )

        if self.scheduled_time:
            self.scheduled_day = (
                self.scheduled_time
                .astimezone(LOCAL_TZ)
                .date()
            )
        else:
            self.scheduled_day = None

        if self.iqd_amount is None:
            self.iqd_amount = 0

        creating = self.pk is None

        if self.status == AppointmentStatus.CANCELLED:
            self.queue_number = None

        if not creating:
            old = (
                Appointment.objects.filter(pk=self.pk)
                .only(
                    "doctor_id",
                    "scheduled_day",
                    "status",
                    "queue_number",
                )
                .first()
            )

            doctor_or_day_changed = bool(
                old
                and (
                    old.doctor_id != self.doctor_id
                    or old.scheduled_day
                    != self.scheduled_day
                )
            )

            became_active = bool(
                old
                and old.status
                == AppointmentStatus.CANCELLED
                and self.status
                != AppointmentStatus.CANCELLED
            )

            needs_queue = bool(
                self.scheduled_time
                and self.status
                != AppointmentStatus.CANCELLED
                and (
                    doctor_or_day_changed
                    or became_active
                    or self.queue_number is None
                )
            )

            if needs_queue:
                with transaction.atomic():
                    Doctor.objects.select_for_update().get(
                        pk=self.doctor_id
                    )

                    self.queue_number = (
                        self._compute_next_queue_number()
                    )

                    self.full_clean()

                    return super().save(
                        *args,
                        **kwargs,
                    )

            self.full_clean()

            return super().save(
                *args,
                **kwargs,
            )

        if (
            not self.scheduled_time
            or self.status
            == AppointmentStatus.CANCELLED
        ):
            self.full_clean()

            return super().save(
                *args,
                **kwargs,
            )

        with transaction.atomic():
            Doctor.objects.select_for_update().get(
                pk=self.doctor_id
            )

            self.queue_number = (
                self._compute_next_queue_number()
            )

            self.full_clean()

            return super().save(
                *args,
                **kwargs,
            )

    def restore(self):
        self.is_deleted = False
        self.deleted_at = None
        self.deleted_by = None
        self.save()

    def __str__(self):
        patient_name = getattr(
            self.patient,
            "full_name",
            str(self.patient),
        )

        doctor_user = getattr(
            self.doctor,
            "user",
            None,
        )

        doctor_name = (
            (
                doctor_user.get_full_name()
                if doctor_user
                else ""
            )
            or (
                doctor_user.username
                if doctor_user
                else ""
            )
            or "Doctor"
        )

        queue = (
            f"#{self.queue_number}"
            if self.queue_number
            else "—"
        )

        amount = (
            f"{int(self.iqd_amount):,} IQD"
            if self.iqd_amount is not None
            else "0 IQD"
        )

        location = ""

        if self.branch_id:
            location = f" | {self.branch.name}"
        elif self.hospital_id:
            location = f" | {self.hospital.name}"

        return (
            f"{patient_name} → Dr. {doctor_name} "
            f"({queue}) | {amount}{location}"
        )


class PatientBookingRequest(models.Model):
    full_name = models.CharField(
        max_length=100,
    )

    date_of_birth = models.DateField(
        blank=True,
        null=True,
    )

    contact_info = models.CharField(
        max_length=200,
    )

    doctor = models.ForeignKey(
        Doctor,
        on_delete=models.CASCADE,
        related_name="booking_requests",
    )

    hospital = models.ForeignKey(
        Hospital,
        on_delete=models.PROTECT,
        related_name="booking_requests",
        null=True,
        blank=True,
    )

    branch = models.ForeignKey(
        Branch,
        on_delete=models.PROTECT,
        related_name="booking_requests",
        null=True,
        blank=True,
    )

    department = models.ForeignKey(
        Department,
        on_delete=models.PROTECT,
        related_name="booking_requests",
        null=True,
        blank=True,
    )

    scheduled_time = models.DateTimeField(
        db_index=True,
    )

    submitted_at = models.DateTimeField(
        auto_now_add=True,
        db_index=True,
    )

    status = models.CharField(
        max_length=20,
        choices=BookingRequestStatus.choices,
        default=BookingRequestStatus.PENDING,
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

    seen_by_secretary = models.BooleanField(
        default=False,
        db_index=True,
        help_text=_(
            "Marked as True once a secretary "
            "has viewed this request."
        ),
    )

    seen_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name=_("Seen at"),
    )

    class Meta:
        ordering = ["-submitted_at", "pk"]

        indexes = [
            models.Index(
                fields=[
                    "hospital",
                    "branch",
                    "scheduled_time",
                ],
                name="idx_request_hosp_branch",
            ),
            models.Index(
                fields=[
                    "department",
                    "status",
                    "scheduled_time",
                ],
                name="idx_request_dept_status",
            ),
        ]

    def clean(self):
        super().clean()

        errors = _get_location_validation_errors(self)

        if not self.scheduled_time:
            if errors:
                raise ValidationError(errors)

            return

        if not self.doctor_id:
            if errors:
                raise ValidationError(errors)

            return

        aware = _to_local_aware(
            self.scheduled_time
        )

        self.scheduled_time = aware

        time_changed = True
        doctor_changed = True

        if self.pk:
            old = (
                PatientBookingRequest.objects
                .filter(pk=self.pk)
                .only(
                    "scheduled_time",
                    "doctor_id",
                )
                .first()
            )

            if old:
                old_time = (
                    _to_local_aware(
                        old.scheduled_time
                    )
                    if old.scheduled_time
                    else None
                )

                time_changed = old_time != aware
                doctor_changed = (
                    old.doctor_id != self.doctor_id
                )

        if (
            self.pk is None
            or time_changed
            or doctor_changed
        ):
            if aware < _now_local() - PAST_MARGIN:
                errors["scheduled_time"] = _(
                    "Requested time is in the past."
                )

        if (
            BOOKING_REQUEST_BLOCK_CONFLICTS
            and self.doctor_id
            and self.scheduled_time
            and (
                self.pk is None
                or time_changed
                or doctor_changed
            )
        ):
            conflict_exists = (
                Appointment.objects.filter(
                    doctor_id=self.doctor_id,
                    scheduled_time=aware,
                )
                .exclude(
                    status=AppointmentStatus.CANCELLED
                )
                .exists()
            )

            if conflict_exists:
                errors["scheduled_time"] = _(
                    "This time is already allocated "
                    "for this doctor."
                )

        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        creating = self.pk is None

        _populate_location(self)

        self.scheduled_time = _to_local_aware(
            self.scheduled_time
        )

        self.full_clean()

        super().save(
            *args,
            **kwargs,
        )

        if creating:
            try:
                doctor_user = getattr(
                    self.doctor,
                    "user",
                    None,
                )

                doctor_name = (
                    (
                        doctor_user.get_full_name()
                        if doctor_user
                        else ""
                    )
                    or (
                        doctor_user.username
                        if doctor_user
                        else ""
                    )
                    or "Doctor"
                )

                location_name = ""

                if self.branch_id:
                    location_name = (
                        f" at {self.branch.name}"
                    )
                elif self.hospital_id:
                    location_name = (
                        f" at {self.hospital.name}"
                    )

                Notification.objects.create(
                    recipient=doctor_user,
                    notification_type=(
                        Notification.Types.BOOKING_REQUEST
                    ),
                    title=_("New Patient Booking"),
                    message=(
                        f"{self.full_name} requested "
                        f"an appointment with "
                        f"Dr. {doctor_name}"
                        f"{location_name} on "
                        f"{self.scheduled_time:%Y-%m-%d %I:%M %p}."
                    ),
                    related_booking_request=self,
                )
            except Exception:
                pass

    def __str__(self):
        doctor_user = getattr(
            self.doctor,
            "user",
            None,
        )

        doctor_name = (
            (
                doctor_user.get_full_name()
                if doctor_user
                else ""
            )
            or (
                doctor_user.username
                if doctor_user
                else ""
            )
            or "Doctor"
        )

        return (
            f"{self.full_name} → "
            f"Dr. {doctor_name} @ "
            f"{self.scheduled_time:%Y-%m-%d %H:%M} "
            f"({self.status})"
        )


class Notification(models.Model):
    class Types(models.TextChoices):
        BOOKING_REQUEST = (
            "booking_request",
            _("Booking Request"),
        )
        PHARMACY = "pharmacy", _("Pharmacy")
        SYSTEM = "system", _("System")

    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="clinic_notifications",
    )

    notification_type = models.CharField(
        max_length=30,
        choices=Types.choices,
        default=Types.SYSTEM,
        db_index=True,
    )

    title = models.CharField(
        max_length=200,
    )

    message = models.TextField()

    action_url = models.CharField(
        max_length=500,
        blank=True,
    )

    is_read = models.BooleanField(
        default=False,
        db_index=True,
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
        db_index=True,
    )

    related_booking_request = models.ForeignKey(
        "PatientBookingRequest",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="notifications",
    )

    class Meta:
        ordering = ["-created_at", "pk"]

    def mark_as_read(self):
        if not self.is_read:
            self.is_read = True
            self.save(update_fields=["is_read"])

    def __str__(self):
        state = (
            _("Read")
            if self.is_read
            else _("Unread")
        )

        return f"{self.title} — {state}"
