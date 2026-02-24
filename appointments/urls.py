# appointments/urls.py
from __future__ import annotations

from django.urls import path

from . import views

# -----------------------------------------------------------------------------
# Optional public-booking module support
# -----------------------------------------------------------------------------
# Prefer views_public if your project splits public booking logic there.
# Fallback to views.py implementations when views_public is not available.
try:  # pragma: no cover
    from . import views_public as public_views  # type: ignore

    _public_book = (
        getattr(public_views, "public_book", None)
        or getattr(public_views, "book_appointment_public", None)
    )
    _public_book_success = (
        getattr(public_views, "public_book_success", None)
        or getattr(public_views, "book_appointment_success", None)
    )
except Exception:  # pragma: no cover
    _public_book = None
    _public_book_success = None


def _callable_or_none(obj):
    return obj if callable(obj) else None


PUBLIC_BOOK_VIEW = _callable_or_none(_public_book) or views.book_appointment_public
PUBLIC_BOOK_SUCCESS_VIEW = _callable_or_none(_public_book_success) or views.book_appointment_success

app_name = "appointments"

urlpatterns = [
    # =========================================================================
    # PUBLIC - Queue Display (waiting screen)
    # =========================================================================
    path("public/queue/", views.queue_display, name="queue_display"),
    path("public/queue", views.queue_display),  # alias (no slash)

    # Public queue JSON API
    path("public/queue.json/", views.queue_public_api, name="queue_public_api"),
    path("public/queue.json", views.queue_public_api),  # alias (no slash)

    # =========================================================================
    # PUBLIC - Self Booking (no login)
    # =========================================================================
    # Canonical names (recommended)
    path("book/", PUBLIC_BOOK_VIEW, name="book_appointment_public"),
    path("book/<int:doctor_id>/", PUBLIC_BOOK_VIEW, name="book_appointment_public_with_doctor"),
    path("book/success/", PUBLIC_BOOK_SUCCESS_VIEW, name="book_appointment_success"),

    # Legacy aliases (for old templates/tests/links)
    path("book/", PUBLIC_BOOK_VIEW, name="public_book"),
    path("book/<int:doctor_id>/", PUBLIC_BOOK_VIEW, name="public_book_with_doctor"),
    path("book/success/", PUBLIC_BOOK_SUCCESS_VIEW, name="public_book_success"),
    path("book/success/", PUBLIC_BOOK_SUCCESS_VIEW, name="book_success"),

    # =========================================================================
    # PATIENT PORTAL (logged-in patient)
    # =========================================================================
    path("patient/doctor/<int:doctor_id>/book/", views.book_patient, name="book_patient"),
    path("patient/my/", views.my_appointments, name="my_appointments"),

    # =========================================================================
    # SECRETARY / INTERNAL DASHBOARD
    # =========================================================================
    path("secretary/", views.secretary_dashboard, name="secretary_dashboard"),
    path("secretary/settings/", views.secretary_settings, name="secretary_settings"),

    # =========================================================================
    # SECRETARY REPORTS
    # =========================================================================
    path("secretary/reports/", views.secretary_reports, name="secretary_reports"),
    path("secretary/reports/export/", views.reports_export, name="reports_export"),

    # Legacy aliases
    path("secretary/reports-legacy/", views.secretary_reports, name="reports"),
    path("secretary/reports-legacy/export/", views.reports_export, name="export_reports"),

    # =========================================================================
    # APPOINTMENT CRUD / WORKFLOW (secretary + allowed staff)
    # =========================================================================
    path("secretary/appointments/", views.appointment_list, name="appointment_list"),
    path("secretary/appointments/create/", views.create_appointment, name="create_appointment"),
    path("secretary/appointments/<int:pk>/ticket/", views.appointment_ticket, name="appointment_ticket"),
    path("secretary/appointments/<int:pk>/edit/", views.edit_appointment, name="edit_appointment"),
    path("secretary/appointments/<int:pk>/cancel/", views.cancel_appointment, name="cancel_appointment"),
    path("secretary/appointments/<int:pk>/delete/", views.delete_appointment, name="delete_appointment"),

    # Confirm / approve appointment status
    path("secretary/appointments/<int:pk>/confirm/", views.confirm_appointment, name="confirm_appointment"),
    path("secretary/appointments/<int:pk>/approve/", views.approve_appointment, name="approve_appointment"),

    # =========================================================================
    # RECYCLE BIN (soft delete / restore)
    # =========================================================================
    path("secretary/appointments/recycle-bin/", views.appointment_recycle_bin, name="appointment_recycle_bin"),
    path("secretary/appointments/<int:pk>/restore/", views.restore_appointment, name="restore_appointment"),
    path("secretary/appointments/<int:pk>/hard-delete/", views.hard_delete_appointment, name="hard_delete_appointment"),

    # Legacy aliases (older code may reverse these)
    path("secretary/appointments-legacy/", views.appointment_list, name="list"),
    path("secretary/appointments-legacy/create/", views.create_appointment, name="create"),
    path("secretary/appointments-legacy/<int:pk>/ticket/", views.appointment_ticket, name="ticket"),
    path("secretary/appointments-legacy/<int:pk>/edit/", views.edit_appointment, name="edit"),
    path("secretary/appointments-legacy/<int:pk>/cancel/", views.cancel_appointment, name="cancel"),
    path("secretary/appointments-legacy/<int:pk>/delete/", views.delete_appointment, name="delete"),

    # =========================================================================
    # BOOKING REQUESTS (public/patient requests -> secretary approval)
    # =========================================================================
    path("secretary/booking-requests/", views.booking_requests_list, name="booking_requests_list"),
    path("secretary/booking-requests/<int:pk>/approve/", views.approve_booking_request, name="approve_booking_request"),
    path("secretary/booking-requests/<int:pk>/reject/", views.reject_booking_request, name="reject_booking_request"),

    # Legacy approve path
    path("secretary/booking/<int:pk>/approve/", views.approve_booking_request, name="approve_booking_request_legacy"),

    # =========================================================================
    # INTERNAL QUEUE APIs (secretary/staff)
    # =========================================================================
    path("secretary/queue.json/", views.queue_number_api, name="queue_number_api"),
    path("secretary/queue.json", views.queue_number_api),  # alias (no slash)

    path("secretary/queue/current.json/", views.current_patient_api, name="current_patient_api"),
    path("secretary/queue/current.json", views.current_patient_api),  # alias (no slash)

    path("secretary/queue/call-next/<int:doctor_id>/", views.call_next_api, name="call_next_api"),
    path("secretary/queue/call-next/<int:doctor_id>/", views.call_next_api, name="call_next_queue"),  # legacy alias name

    # =========================================================================
    # NOTIFICATIONS (secretary bell / list)
    # =========================================================================
    path("secretary/notifications/new/", views.new_booking_requests_api, name="new_booking_requests_api"),
    path("secretary/notifications/", views.notifications_list, name="notifications_list"),
    path("secretary/notifications/<int:pk>/read/", views.mark_notification_read, name="mark_notification_read"),
    path("secretary/notifications/read-all/", views.mark_all_notifications_read, name="mark_all_notifications_read"),
]