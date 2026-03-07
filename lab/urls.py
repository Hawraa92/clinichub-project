from django.urls import path
from django.views.generic import RedirectView

from . import views

app_name = "lab"

urlpatterns = [
    # =========================
    # Default entry: /lab/ -> /lab/dashboard/
    # =========================
    path(
        "",
        RedirectView.as_view(pattern_name="lab:dashboard", permanent=False),
        name="index",
    ),

    # =========================
    # Lab: Dashboard + Settings
    # =========================
    path("dashboard/", views.lab_dashboard, name="dashboard"),
    path("settings/", views.lab_settings, name="lab_settings"),

    # ✅ API: pending-count (for red inbox badge in lab interface)
    path("pending-count/", views.lab_pending_count_api, name="lab_pending_count_api"),

    # =========================
    # Doctor: Lab Orders (Create + Inbox + Detail)
    # =========================
    path("doctor/inbox/", views.doctor_orders_inbox, name="doctor_orders_inbox"),

    # ✅ API: ready-count (for red badge + notifications for doctor)
    path("doctor/ready-count/", views.doctor_ready_count_api, name="doctor_ready_count_api"),

    # Create order (general)
    path("doctor/create/", views.doctor_create_lab_order, name="doctor_create_order"),

    # Create order for a specific patient
    path(
        "doctor/create/<int:patient_id>/",
        views.doctor_create_lab_order,
        name="doctor_create_order_patient",
    ),

    # Doctor order detail
    path(
        "doctor/order/<int:order_id>/",
        views.doctor_order_detail,
        name="doctor_order_detail",
    ),

    # Optional alias
    path(
        "doctor/orders/<int:order_id>/",
        views.doctor_order_detail,
        name="doctor_order_detail_alias",
    ),

    # =========================
    # Lab: Inbox + Order Detail
    # =========================
    path("inbox/", views.lab_inbox, name="lab_inbox"),

    # Lab order detail
    path(
        "order/<int:order_id>/",
        views.lab_order_detail,
        name="lab_order_detail",
    ),

    # Optional alias
    path(
        "orders/<int:order_id>/",
        views.lab_order_detail,
        name="lab_order_detail_alias",
    ),
]