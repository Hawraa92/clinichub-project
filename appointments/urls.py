from __future__ import annotations

from django.urls import path

from . import views


app_name = "appointments"


urlpatterns = [
    # Public waiting-room display
    path(
        "public/queue/",
        views.queue_display,
        name="queue_display",
    ),
    path(
        "public/queue.json",
        views.queue_public_api,
        name="queue_public_api",
    ),

    # Patient portal
    path(
        "patient/doctor/<int:doctor_id>/book/",
        views.book_patient,
        name="book_patient",
    ),
    path(
        "patient/my/",
        views.my_appointments,
        name="my_appointments",
    ),

    # Notification center
    path(
        "notifications/",
        views.notifications_list,
        name="notifications_list",
    ),
    path(
        "notifications/api/",
        views.notifications_api,
        name="notifications_api",
    ),
    path(
        "notifications/read-all/",
        views.notifications_mark_all_read,
        name="notifications_mark_all_read",
    ),
    path(
        "notifications/<int:pk>/open/",
        views.notification_open,
        name="notification_open",
    ),
    path(
        "notifications/<int:pk>/read/",
        views.notification_mark_read,
        name="notification_mark_read",
    ),

    # Secretary dashboard and settings
    path(
        "secretary/",
        views.secretary_dashboard,
        name="secretary_dashboard",
    ),
    path(
        "secretary/settings/",
        views.secretary_settings,
        name="secretary_settings",
    ),

    # Secretary reports
    path(
        "secretary/reports/",
        views.secretary_reports,
        name="secretary_reports",
    ),
    path(
        "secretary/reports/export/",
        views.reports_export,
        name="reports_export",
    ),

    # Legacy report aliases
    path(
        "secretary/reports-legacy/",
        views.secretary_reports,
        name="reports",
    ),
    path(
        "secretary/reports-legacy/export/",
        views.reports_export,
        name="export_reports",
    ),

    # Appointment management
    path(
        "secretary/appointments/",
        views.appointment_list,
        name="appointment_list",
    ),
    path(
        "secretary/appointments/create/",
        views.create_appointment,
        name="create_appointment",
    ),
    path(
        "secretary/appointments/<int:pk>/ticket/",
        views.appointment_ticket,
        name="appointment_ticket",
    ),
    path(
        "secretary/appointments/<int:pk>/edit/",
        views.edit_appointment,
        name="edit_appointment",
    ),
    path(
        "secretary/appointments/<int:pk>/cancel/",
        views.cancel_appointment,
        name="cancel_appointment",
    ),
    path(
        "secretary/appointments/<int:pk>/delete/",
        views.delete_appointment,
        name="delete_appointment",
    ),

    # Recycle bin
    path(
        "secretary/appointments/recycle-bin/",
        views.appointment_recycle_bin,
        name="appointment_recycle_bin",
    ),
    path(
        "secretary/appointments/<int:pk>/restore/",
        views.restore_appointment,
        name="restore_appointment",
    ),
    path(
        "secretary/appointments/<int:pk>/hard-delete/",
        views.hard_delete_appointment,
        name="hard_delete_appointment",
    ),

    # Legacy appointment aliases
    path(
        "secretary/appointments-legacy/",
        views.appointment_list,
        name="list",
    ),
    path(
        "secretary/appointments-legacy/create/",
        views.create_appointment,
        name="create",
    ),
    path(
        "secretary/appointments-legacy/<int:pk>/ticket/",
        views.appointment_ticket,
        name="ticket",
    ),
    path(
        "secretary/appointments-legacy/<int:pk>/edit/",
        views.edit_appointment,
        name="edit",
    ),
    path(
        "secretary/appointments-legacy/<int:pk>/cancel/",
        views.cancel_appointment,
        name="cancel",
    ),
    path(
        "secretary/appointments-legacy/<int:pk>/delete/",
        views.delete_appointment,
        name="delete",
    ),

    # Appointment confirmation
    path(
        "secretary/appointments/<int:pk>/confirm/",
        views.confirm_appointment,
        name="confirm_appointment",
    ),
    path(
        "secretary/appointments/<int:pk>/approve/",
        views.approve_appointment,
        name="approve_appointment",
    ),

    # External booking requests
    path(
        "secretary/booking-requests/",
        views.booking_requests_list,
        name="booking_requests_list",
    ),
    path(
        "secretary/booking-requests/<int:pk>/approve/",
        views.approve_booking_request,
        name="approve_booking_request",
    ),
    path(
        "secretary/booking/<int:pk>/approve/",
        views.approve_booking_request,
        name="approve_booking_request_legacy",
    ),

    # Internal queue APIs
    path(
        "secretary/queue.json",
        views.queue_number_api,
        name="queue_number_api",
    ),
    path(
        "secretary/queue/current.json",
        views.current_patient_api,
        name="current_patient_api",
    ),
    path(
        "secretary/queue/call-next/<int:doctor_id>/",
        views.call_next_api,
        name="call_next_api",
    ),

    # Legacy secretary booking notification API
    path(
        "secretary/notifications/new/",
        views.new_booking_requests_api,
        name="new_booking_requests_api",
    ),
]
