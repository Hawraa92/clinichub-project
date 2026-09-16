from datetime import date

from django.contrib import admin
from django.utils import timezone
from django.utils.html import format_html

from .models import (
    Appointment,
    AppointmentStatus,
    BookingRequestStatus,
    Notification,
    PatientBookingRequest,
)


class AppointmentDateRangeFilter(admin.SimpleListFilter):
    title = "Time Range"
    parameter_name = "time_range"

    def lookups(self, request, model_admin):
        return [
            ("past", "Past"),
            ("today", "Today"),
            ("future", "Future"),
        ]

    def queryset(self, request, queryset):
        value = self.value()

        if not value:
            return queryset

        today = timezone.localdate()

        if value == "past":
            return queryset.filter(scheduled_time__date__lt=today)

        if value == "today":
            return queryset.filter(scheduled_time__date=today)

        if value == "future":
            return queryset.filter(scheduled_time__date__gt=today)

        return queryset


@admin.register(Appointment)
class AppointmentAdmin(admin.ModelAdmin):
    list_display = (
        "get_patient_name",
        "get_patient_age",
        "get_doctor_name",
        "hospital",
        "branch",
        "department",
        "scheduled_time",
        "queue_number",
        "amount_iqd",
        "colored_status",
    )

    list_filter = (
        "hospital",
        "branch",
        "department",
        "doctor",
        "status",
        AppointmentDateRangeFilter,
    )

    search_fields = (
        "patient__full_name",
        "doctor__full_name",
        "doctor__user__email",
        "doctor__user__first_name",
        "doctor__user__last_name",
        "hospital__name",
        "hospital__code",
        "branch__name",
        "branch__code",
        "department__name",
        "department__code",
        "notes",
    )

    list_select_related = (
        "patient",
        "doctor",
        "doctor__user",
        "hospital",
        "branch",
        "department",
    )

    autocomplete_fields = (
        "patient",
        "doctor",
        "hospital",
        "branch",
        "department",
    )

    readonly_fields = (
        "queue_number",
        "scheduled_day",
        "created_at",
    )

    fieldsets = (
        (
            "Appointment Details",
            {
                "fields": (
                    "patient",
                    "doctor",
                    "hospital",
                    "branch",
                    "department",
                    "scheduled_time",
                    "iqd_amount",
                    "status",
                    "notes",
                )
            },
        ),
        (
            "System Information",
            {
                "fields": (
                    "queue_number",
                    "scheduled_day",
                    "created_at",
                ),
                "classes": ("collapse",),
            },
        ),
    )

    date_hierarchy = "scheduled_time"
    ordering = ("-scheduled_time",)
    list_per_page = 50

    actions = (
        "mark_completed",
        "mark_cancelled",
    )

    @admin.display(
        description="Patient Name",
        ordering="patient__full_name",
    )
    def get_patient_name(self, obj):
        return getattr(obj.patient, "full_name", "—")

    @admin.display(description="Patient Age")
    def get_patient_age(self, obj):
        if not obj.patient:
            return "—"

        patient_age = getattr(obj.patient, "age", None)

        if patient_age is not None:
            return patient_age

        date_of_birth = getattr(
            obj.patient,
            "date_of_birth",
            None,
        )

        if not date_of_birth:
            return "—"

        today = date.today()

        return (
            today.year
            - date_of_birth.year
            - (
                (today.month, today.day)
                < (date_of_birth.month, date_of_birth.day)
            )
        )

    @admin.display(
        description="Doctor",
        ordering="doctor__full_name",
    )
    def get_doctor_name(self, obj):
        if not obj.doctor:
            return "—"

        if obj.doctor.full_name:
            return obj.doctor.full_name

        user = obj.doctor.user

        return (
            user.get_full_name()
            or user.first_name
            or user.username
            or user.email
        )

    @admin.display(
        description="Amount (IQD)",
        ordering="iqd_amount",
    )
    def amount_iqd(self, obj):
        if obj.iqd_amount is None:
            return "0"

        try:
            return f"{int(obj.iqd_amount):,}"
        except (TypeError, ValueError):
            return obj.iqd_amount

    @admin.display(
        description="Status",
        ordering="status",
    )
    def colored_status(self, obj):
        color_map = {
            AppointmentStatus.PENDING: "#ffc107",
            AppointmentStatus.COMPLETED: "#28a745",
            AppointmentStatus.CANCELLED: "#dc3545",
        }

        color = color_map.get(
            obj.status,
            "#6c757d",
        )

        return format_html(
            (
                '<span style="padding:3px 8px;'
                "border-radius:4px;"
                "background:{};"
                'color:#fff;font-size:12px;">{}</span>'
            ),
            color,
            obj.get_status_display(),
        )

    @admin.action(
        description="Mark selected appointments as completed"
    )
    def mark_completed(self, request, queryset):
        updated = queryset.exclude(
            status=AppointmentStatus.COMPLETED
        ).update(
            status=AppointmentStatus.COMPLETED
        )

        self.message_user(
            request,
            f"{updated} appointment(s) marked as completed.",
        )

    @admin.action(
        description="Mark selected appointments as cancelled"
    )
    def mark_cancelled(self, request, queryset):
        updated = 0

        for appointment in queryset.iterator():
            if appointment.status == AppointmentStatus.CANCELLED:
                continue

            appointment.status = AppointmentStatus.CANCELLED
            appointment.save()
            updated += 1

        self.message_user(
            request,
            f"{updated} appointment(s) marked as cancelled.",
        )


@admin.register(PatientBookingRequest)
class PatientBookingRequestAdmin(admin.ModelAdmin):
    list_display = (
        "full_name",
        "doctor",
        "hospital",
        "branch",
        "department",
        "scheduled_time",
        "colored_status",
        "submitted_at",
    )

    list_filter = (
        "hospital",
        "branch",
        "department",
        "status",
        "doctor",
    )

    search_fields = (
        "full_name",
        "contact_info",
        "doctor__full_name",
        "doctor__user__email",
        "doctor__user__first_name",
        "doctor__user__last_name",
        "hospital__name",
        "branch__name",
        "department__name",
    )

    list_select_related = (
        "doctor",
        "doctor__user",
        "hospital",
        "branch",
        "department",
        "patient",
        "user",
    )

    autocomplete_fields = (
        "doctor",
        "hospital",
        "branch",
        "department",
        "patient",
        "user",
    )

    readonly_fields = (
        "submitted_at",
        "seen_at",
    )

    fieldsets = (
        (
            "Patient Information",
            {
                "fields": (
                    "full_name",
                    "date_of_birth",
                    "contact_info",
                    "patient",
                    "user",
                )
            },
        ),
        (
            "Booking Information",
            {
                "fields": (
                    "doctor",
                    "hospital",
                    "branch",
                    "department",
                    "scheduled_time",
                    "status",
                )
            },
        ),
        (
            "Secretary Information",
            {
                "fields": (
                    "seen_by_secretary",
                    "seen_at",
                    "submitted_at",
                ),
                "classes": ("collapse",),
            },
        ),
    )

    date_hierarchy = "submitted_at"
    ordering = ("-submitted_at",)
    list_per_page = 50

    actions = (
        "mark_as_confirmed",
        "mark_as_rejected",
    )

    @admin.display(
        description="Status",
        ordering="status",
    )
    def colored_status(self, obj):
        color_map = {
            BookingRequestStatus.PENDING: "#ffc107",
            BookingRequestStatus.REQUESTED: "#17a2b8",
            BookingRequestStatus.CONFIRMED: "#28a745",
            BookingRequestStatus.REJECTED: "#dc3545",
        }

        color = color_map.get(
            obj.status,
            "#6c757d",
        )

        return format_html(
            (
                '<span style="padding:3px 8px;'
                "border-radius:4px;"
                "background:{};"
                'color:#fff;font-size:12px;">{}</span>'
            ),
            color,
            obj.get_status_display(),
        )

    @admin.action(
        description="Mark selected booking requests as confirmed"
    )
    def mark_as_confirmed(self, request, queryset):
        updated = queryset.exclude(
            status=BookingRequestStatus.CONFIRMED
        ).update(
            status=BookingRequestStatus.CONFIRMED
        )

        self.message_user(
            request,
            f"{updated} booking request(s) marked as confirmed.",
        )

    @admin.action(
        description="Mark selected booking requests as rejected"
    )
    def mark_as_rejected(self, request, queryset):
        updated = queryset.exclude(
            status=BookingRequestStatus.REJECTED
        ).update(
            status=BookingRequestStatus.REJECTED
        )

        self.message_user(
            request,
            f"{updated} booking request(s) marked as rejected.",
        )


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = (
        "title",
        "related_booking_request",
        "is_read",
        "created_at",
    )

    list_filter = (
        "is_read",
        "created_at",
    )

    search_fields = (
        "title",
        "message",
        "related_booking_request__full_name",
    )

    readonly_fields = (
        "created_at",
    )

    ordering = (
        "-created_at",
    )

    list_select_related = (
        "related_booking_request",
        "related_booking_request__doctor",
        "related_booking_request__doctor__user",
        "related_booking_request__hospital",
        "related_booking_request__branch",
        "related_booking_request__department",
    )

    actions = (
        "mark_as_read",
        "mark_as_unread",
    )

    list_editable = (
        "is_read",
    )

    list_per_page = 50
    date_hierarchy = "created_at"

    @admin.action(
        description="Mark selected notifications as read"
    )
    def mark_as_read(self, request, queryset):
        updated = queryset.filter(
            is_read=False
        ).update(
            is_read=True
        )

        self.message_user(
            request,
            f"{updated} notification(s) marked as read.",
        )

    @admin.action(
        description="Mark selected notifications as unread"
    )
    def mark_as_unread(self, request, queryset):
        updated = queryset.filter(
            is_read=True
        ).update(
            is_read=False
        )

        self.message_user(
            request,
            f"{updated} notification(s) marked as unread.",
        )