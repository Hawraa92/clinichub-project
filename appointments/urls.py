# appointments/urls.py
from __future__ import annotations

from typing import Any, Callable, Optional

from django.urls import path

from . import views

# =============================================================================
# Helpers
# =============================================================================
ViewCallable = Callable[..., Any]


def _get_view(module: Any, *names: str) -> Optional[ViewCallable]:
    """
    Try multiple attribute names from a module and return the first callable one.
    Useful for backward compatibility across refactors/renames.
    """
    if module is None:
        return None
    for name in names:
        fn = getattr(module, name, None)
        if callable(fn):
            return fn
    return None


def _require_view(fn: Optional[ViewCallable], error: str) -> ViewCallable:
    """Fail fast with a clear message if a view is missing."""
    if fn is None:
        raise ImportError(error)
    return fn


# =============================================================================
# Optional public-booking module support
# =============================================================================
try:  # pragma: no cover
    from . import views_public as public_views  # type: ignore
except Exception:  # pragma: no cover
    public_views = None  # type: ignore[assignment]

PUBLIC_BOOK_VIEW = _require_view(
    (_get_view(public_views, "public_book", "book_appointment_public") if public_views else None)
    or _get_view(views, "book_appointment_public", "public_book"),
    "Could not resolve a public booking view. "
    "Expected one of: views_public.public_book / views_public.book_appointment_public "
    "or views.book_appointment_public / views.public_book",
)

PUBLIC_BOOK_SUCCESS_VIEW = _require_view(
    (_get_view(public_views, "public_book_success", "book_appointment_success") if public_views else None)
    or _get_view(views, "book_appointment_success", "public_book_success", "book_success"),
    "Could not resolve a public booking success view. "
    "Expected one of: views_public.public_book_success / views_public.book_appointment_success "
    "or views.book_appointment_success / views.public_book_success / views.book_success",
)

# Public queue JSON API: prefer a dedicated public endpoint if you have one,
# otherwise fall back to the internal queue API view.
PUBLIC_QUEUE_API_VIEW = _require_view(
    _get_view(views, "queue_public_api", "queue_number_api"),
    "Could not resolve a public queue API view. Expected views.queue_public_api or views.queue_number_api",
)

app_name = "appointments"

# =============================================================================
# URL Patterns
# =============================================================================
urlpatterns = [
    # =========================================================================
    # PUBLIC - Queue Display (waiting screen)
    # =========================================================================
    path("public/queue/", views.queue_display, name="queue_display"),
    path("public/queue.json/", PUBLIC_QUEUE_API_VIEW, name="queue_public_api"),

    # =========================================================================
    # PUBLIC - Self Booking (no login) - canonical routes
    # =========================================================================
    path("book/", PUBLIC_BOOK_VIEW, name="book_appointment_public"),
    path("book/<int:doctor_id>/", PUBLIC_BOOK_VIEW, name="book_appointment_public_with_doctor"),
    path("book/success/", PUBLIC_BOOK_SUCCESS_VIEW, name="book_appointment_success"),

    # =========================================================================
    # ✅ Backward-compatibility aliases for tests / legacy
    # tests expect:
    #   appointments:public_book
    #   appointments:public_book_with_doctor
    #   appointments:book_success
    #
    # IMPORTANT:
    # views_public redirects to "appointments:public_book_success"
    # so we bind that name to the SAME URL as book_success: /book-success/
    # =========================================================================
    path("public-book/", PUBLIC_BOOK_VIEW, name="public_book"),
    path("public-book/<int:doctor_id>/", PUBLIC_BOOK_VIEW, name="public_book_with_doctor"),

    # ✅ both names resolve to /appointments/book-success/
    path("book-success/", PUBLIC_BOOK_SUCCESS_VIEW, name="book_success"),
    path("book-success/", PUBLIC_BOOK_SUCCESS_VIEW, name="public_book_success"),

    # (اختياري) نخلي رابط قديم يشتغل إذا عندج ناس تستخدمه
    path("public-book/success/", PUBLIC_BOOK_SUCCESS_VIEW, name="public_book_success_legacy"),

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

    # =========================================================================
    # BOOKING REQUESTS (public/patient requests -> secretary approval)
    # =========================================================================
    path("secretary/booking-requests/", views.booking_requests_list, name="booking_requests_list"),
    path("secretary/booking-requests/<int:pk>/approve/", views.approve_booking_request, name="approve_booking_request"),
    path("secretary/booking-requests/<int:pk>/reject/", views.reject_booking_request, name="reject_booking_request"),

    # =========================================================================
    # INTERNAL QUEUE APIs (secretary/staff)
    # =========================================================================
    path("secretary/queue.json/", views.queue_number_api, name="queue_number_api"),
    path("secretary/queue/current.json/", views.current_patient_api, name="current_patient_api"),
    path("secretary/queue/call-next/<int:doctor_id>/", views.call_next_api, name="call_next_api"),

    # =========================================================================
    # NOTIFICATIONS (secretary bell / list)
    # =========================================================================
    path("secretary/notifications/new/", views.new_booking_requests_api, name="new_booking_requests_api"),
    path("secretary/notifications/", views.notifications_list, name="notifications_list"),
    path("secretary/notifications/<int:pk>/read/", views.mark_notification_read, name="mark_notification_read"),
    path("secretary/notifications/read-all/", views.mark_all_notifications_read, name="mark_all_notifications_read"),
]