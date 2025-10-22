# appointments/urls.py — Audited (Phase 2, Unit 1 Compliant)
#
# Key goals:
# - Clear split between PUBLIC (PHI-free) and INTERNAL (secretary-only) endpoints
# - Patient-portal routes (logged-in patients)
# - Legacy alias kept for approve_appointment → confirm_appointment
# - Clean, non-duplicated routes; consistent with the recommended views.py
# ------------------------------------------------------------------

from django.urls import path
from . import views

app_name = "appointments"

urlpatterns = [
    # ---------------- PUBLIC (PHI-free) ----------------
    path("public/queue/", views.queue_display, name="queue_display"),
    path("public/queue.json", views.queue_public_api, name="queue_public_api"),

    # ---------------- Patient Portal ----------------
    path("patient/doctor/<int:doctor_id>/book/", views.book_patient, name="book_patient"),
    path("patient/my/", views.my_appointments, name="my_appointments"),

    # ---------------- Secretary / Internal ----------------
    path("secretary/", views.secretary_dashboard, name="secretary_dashboard"),
    path("secretary/settings/", views.secretary_settings, name="secretary_settings"),

    # CRUD
    path("secretary/appointments/", views.appointment_list, name="appointment_list"),
    path("secretary/appointments/create/", views.create_appointment, name="create_appointment"),
    path("secretary/appointments/<int:pk>/ticket/", views.appointment_ticket, name="appointment_ticket"),
    path("secretary/appointments/<int:pk>/edit/", views.edit_appointment, name="edit_appointment"),
    path("secretary/appointments/<int:pk>/cancel/", views.cancel_appointment, name="cancel_appointment"),
    path("secretary/appointments/<int:pk>/delete/", views.delete_appointment, name="delete_appointment"),

    # Confirmation (no APPROVED state in enum)
    path("secretary/appointments/<int:pk>/confirm/", views.confirm_appointment, name="confirm_appointment"),
    # Legacy alias for backward-compat (optional, points to the same view)
    path("secretary/appointments/<int:pk>/approve/", views.approve_appointment, name="approve_appointment"),

    # Booking request approval
    path("secretary/booking/<int:pk>/approve/", views.approve_booking_request, name="approve_booking_request"),

    # ---------------- Queue APIs (Internal) ----------------
    path("secretary/queue.json", views.queue_number_api, name="queue_number_api"),
    path("secretary/queue/current.json", views.current_patient_api, name="current_patient_api"),
    path("secretary/queue/call-next/<int:doctor_id>/", views.call_next_api, name="call_next_api"),

    # ---------------- Notifications / Bell (Internal) ----------------
    path("secretary/notifications/new/", views.new_booking_requests_api, name="new_booking_requests_api"),
]

# ------------------------------------------------------------------
# Optional: If you have extra public booking or secretary reports views, you may add them back here.
# Ensure public booking pages stay PHI-free and secretary reports are protected in views with @secretary_required.
# ------------------------------------------------------------------
# Example (only if the views exist):
# from . import extra_views
# urlpatterns += [
#     path("public/book/", extra_views.book_appointment_public, name="public_book"),
#     path("public/book/<int:doctor_id>/", extra_views.book_appointment_public, name="public_book_with_doctor"),
#     path("public/book/success/", extra_views.book_success, name="book_success"),
#     path("secretary/reports/", extra_views.secretary_reports, name="secretary_reports"),
#     path("secretary/reports/export/", extra_views.reports_export, name="reports_export"),
# ]
