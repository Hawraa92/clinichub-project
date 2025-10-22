# appointments/admin.py

from django.contrib import admin
from django.utils.html import format_html
from django.utils import timezone
from datetime import date

from .models import (
    Appointment,
    PatientBookingRequest,
    Notification,
    AppointmentStatus,
    BookingRequestStatus,
)


# ---------------------------
# Custom Filters
# ---------------------------
class AppointmentDateRangeFilter(admin.SimpleListFilter):
    title = "Time Range"
    parameter_name = "time_range"

    def lookups(self, request, model_admin):
        return [
            ('past', 'Past'),
            ('today', 'Today'),
            ('future', 'Future'),
        ]

    def queryset(self, request, queryset):
        value = self.value()
        if not value:
            return queryset
        today = timezone.localdate()
        if value == 'past':
            return queryset.filter(scheduled_time__date__lt=today)
        if value == 'today':
            return queryset.filter(scheduled_time__date=today)
        if value == 'future':
            return queryset.filter(scheduled_time__date__gt=today)
        return queryset


# ---------------------------
# Appointment Admin
# ---------------------------
@admin.register(Appointment)
class AppointmentAdmin(admin.ModelAdmin):
    list_display = [
        'get_patient_name',
        'get_patient_age',
        'get_doctor_name',
        'scheduled_time',
        'queue_number',
        'amount_iqd',
        'status',
        'colored_status',
    ]
    list_filter = [
        'doctor',
        'status',
        AppointmentDateRangeFilter,
    ]
    search_fields = [
        'patient__full_name',
        'doctor__user__first_name',
        'doctor__user__last_name',
        'notes',
    ]
    list_select_related = ('patient', 'doctor', 'doctor__user')
    date_hierarchy = 'scheduled_time'
    ordering = ['-scheduled_time']
    readonly_fields = ('queue_number', 'created_at')
    list_per_page = 50

    autocomplete_fields = ('patient', 'doctor')
    list_editable = ('status',)

    actions = ['mark_completed', 'mark_cancelled']

    # ----- Display helpers -----
    @admin.display(description='Patient Name', ordering='patient__full_name')
    def get_patient_name(self, obj):
        return getattr(obj.patient, 'full_name', '—')

    @admin.display(description='Patient Age')
    def get_patient_age(self, obj):
        if obj.patient and hasattr(obj.patient, 'age') and obj.patient.age is not None:
            return obj.patient.age
        dob = getattr(obj.patient, 'date_of_birth', None)
        if dob:
            today = date.today()
            years = today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))
            return years
        return '—'

    @admin.display(description='Doctor', ordering='doctor__user__first_name')
    def get_doctor_name(self, obj):
        # اسم الطبيب المنسّق حتى لو لم يكن __str__ للطبيب مهيء
        u = obj.doctor.user
        return u.get_full_name() or u.first_name or u.username

    @admin.display(description='Amount (IQD)', ordering='iqd_amount')
    def amount_iqd(self, obj):
        try:
            # تنسيق مفصول بالألوف
            return f"{int(obj.iqd_amount):,}"
        except Exception:
            return obj.iqd_amount

    @admin.display(description='Status', ordering='status')
    def colored_status(self, obj):
        color_map = {
            AppointmentStatus.PENDING:   '#ffc107',  # أصفر
            AppointmentStatus.COMPLETED: '#28a745',  # أخضر
            AppointmentStatus.CANCELLED: '#dc3545',  # أحمر
        }
        label = obj.get_status_display()
        color = color_map.get(obj.status, '#6c757d')  # رمادي افتراضي
        return format_html(
            '<span style="padding:2px 6px; border-radius:4px; '
            'background:{}; color:#fff; font-size:12px;">{}</span>',
            color,
            label
        )

    # ----- Actions -----
    @admin.action(description='Mark selected appointments as COMPLETED')
    def mark_completed(self, request, queryset):
        updated = queryset.update(status=AppointmentStatus.COMPLETED)
        self.message_user(request, f"{updated} appointment(s) marked as completed.")

    @admin.action(description='Mark selected appointments as CANCELLED')
    def mark_cancelled(self, request, queryset):
        updated = queryset.update(status=AppointmentStatus.CANCELLED)
        self.message_user(request, f"{updated} appointment(s) marked as cancelled.")


# ---------------------------
# Patient Booking Request Admin
# ---------------------------
@admin.register(PatientBookingRequest)
class PatientBookingRequestAdmin(admin.ModelAdmin):
    list_display = [
        'full_name',
        'doctor',
        'scheduled_time',
        'status',
        'colored_status',
        'submitted_at',
    ]
    list_filter = ['status', 'doctor']
    search_fields = [
        'full_name',
        'contact_info',
        'doctor__user__first_name',
        'doctor__user__last_name',
    ]
    list_select_related = ('doctor', 'doctor__user')
    date_hierarchy = 'submitted_at'
    ordering = ['-submitted_at']
    readonly_fields = ('submitted_at',)
    list_per_page = 50

    autocomplete_fields = ('doctor',)
    list_editable = ('status',)

    actions = ['mark_as_confirmed', 'mark_as_rejected']

    @admin.display(description='Status', ordering='status')
    def colored_status(self, obj):
        color_map = {
            BookingRequestStatus.PENDING:   '#ffc107',
            BookingRequestStatus.CONFIRMED: '#28a745',
            BookingRequestStatus.REJECTED:  '#dc3545',
        }
        label = obj.get_status_display()
        color = color_map.get(obj.status, '#6c757d')
        return format_html(
            '<span style="padding:2px 6px; border-radius:4px; '
            'background:{}; color:#fff; font-size:12px;">{}</span>',
            color,
            label
        )

    @admin.action(description='Mark selected booking requests as CONFIRMED')
    def mark_as_confirmed(self, request, queryset):
        updated = queryset.update(status=BookingRequestStatus.CONFIRMED)
        self.message_user(request, f"{updated} booking request(s) marked as confirmed.")

    @admin.action(description='Mark selected booking requests as REJECTED')
    def mark_as_rejected(self, request, queryset):
        updated = queryset.update(status=BookingRequestStatus.REJECTED)
        self.message_user(request, f"{updated} booking request(s) marked as rejected.")


# ---------------------------
# Notification Admin
# ---------------------------
@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ['title', 'related_booking_request', 'is_read', 'created_at']
    list_filter = ['is_read']
    search_fields = ['title', 'message']
    readonly_fields = ['created_at']
    ordering = ['-created_at']
    # ↓ إضافة user لتقليل الاستعلامات في __str__ للـ booking request
    list_select_related = (
        'related_booking_request',
        'related_booking_request__doctor',
        'related_booking_request__doctor__user',
    )
    actions = ['mark_as_read', 'mark_as_unread']
    list_per_page = 50

    list_editable = ('is_read',)
    date_hierarchy = 'created_at'

    @admin.action(description='Mark selected notifications as READ')
    def mark_as_read(self, request, queryset):
        updated = queryset.filter(is_read=False).update(is_read=True)
        self.message_user(request, f"{updated} notification(s) marked as read.")

    @admin.action(description='Mark selected notifications as UNREAD')
    def mark_as_unread(self, request, queryset):
        updated = queryset.filter(is_read=True).update(is_read=False)
        self.message_user(request, f"{updated} notification(s) marked as unread.")
