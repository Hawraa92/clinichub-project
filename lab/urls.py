"""
URL configuration for the ClinicHub laboratory module.

Route-level permissions provide the first security layer.  Object ownership
and method-specific permissions (especially POST actions) must also be checked
inside ``lab/views.py``.
"""

from __future__ import annotations

from collections.abc import Callable
from django.contrib.auth.decorators import login_required, permission_required
from django.http import HttpResponse
from django.urls import path
from django.views.generic import RedirectView

from . import views


app_name = "lab"


def protected_view(
    view_func: Callable[..., HttpResponse],
    permission: str,
) -> Callable[..., HttpResponse]:
    """
    Require authentication and one Django model permission.

    ``raise_exception=True`` sends authenticated users who do not have the
    permission to ClinicHub's custom 403 page instead of silently redirecting
    them.
    """

    permission_checked_view = permission_required(
        permission,
        raise_exception=True,
    )(view_func)

    return login_required(permission_checked_view)


urlpatterns = [
    # ---------------------------------------------------------
    # Default entry: /lab/ -> /lab/dashboard/
    # The destination itself is permission-protected below.
    # ---------------------------------------------------------
    path(
        "",
        RedirectView.as_view(
            pattern_name="lab:dashboard",
            permanent=False,
        ),
        name="index",
    ),

    # ---------------------------------------------------------
    # Laboratory dashboard and settings
    # ---------------------------------------------------------
    path(
        "dashboard/",
        protected_view(
            views.lab_dashboard,
            "lab.view_laborder",
        ),
        name="dashboard",
    ),
    path(
        "settings/",
        protected_view(
            views.lab_settings,
            "lab.view_labsettings",
        ),
        name="lab_settings",
    ),

    # ---------------------------------------------------------
    # Doctor laboratory orders
    # ---------------------------------------------------------
    path(
        "doctor/inbox/",
        protected_view(
            views.doctor_orders_inbox,
            "lab.view_laborder",
        ),
        name="doctor_orders_inbox",
    ),
    path(
        "doctor/ready-count/",
        protected_view(
            views.doctor_ready_count_api,
            "lab.view_laborder",
        ),
        name="doctor_ready_count_api",
    ),
    path(
        "doctor/create/",
        protected_view(
            views.doctor_create_lab_order,
            "lab.add_laborder",
        ),
        name="doctor_create_order",
    ),
    path(
        "doctor/create/<int:patient_id>/",
        protected_view(
            views.doctor_create_lab_order,
            "lab.add_laborder",
        ),
        name="doctor_create_order_patient",
    ),
    path(
        "doctor/order/<int:order_id>/",
        protected_view(
            views.doctor_order_detail,
            "lab.view_laborder",
        ),
        name="doctor_order_detail",
    ),
    path(
        "doctor/order/<int:order_id>/doctor-attachment/preview/",
        protected_view(
            views.doctor_order_doctor_attachment_file,
            "lab.view_laborder",
        ),
        {"inline": True},
        name="doctor_order_doctor_attachment_preview",
    ),
    path(
        "doctor/order/<int:order_id>/doctor-attachment/download/",
        protected_view(
            views.doctor_order_doctor_attachment_file,
            "lab.view_laborder",
        ),
        {"inline": False},
        name="doctor_order_doctor_attachment_download",
    ),
    path(
        "doctor/order/<int:order_id>/result-attachment/preview/",
        protected_view(
            views.doctor_result_attachment_file,
            "lab.view_labresult",
        ),
        {"inline": True},
        name="doctor_result_attachment_preview",
    ),
    path(
        "doctor/order/<int:order_id>/result-attachment/download/",
        protected_view(
            views.doctor_result_attachment_file,
            "lab.view_labresult",
        ),
        {"inline": False},
        name="doctor_result_attachment_download",
    ),
    path(
        "doctor/orders/<int:order_id>/",
        protected_view(
            views.doctor_order_detail,
            "lab.view_laborder",
        ),
        name="doctor_order_detail_alias",
    ),

    # ---------------------------------------------------------
    # Laboratory staff inbox and order details
    # ---------------------------------------------------------
    path(
        "inbox/",
        protected_view(
            views.lab_inbox,
            "lab.view_laborder",
        ),
        name="lab_inbox",
    ),
    path(
        "order/<int:order_id>/",
        protected_view(
            views.lab_order_detail,
            "lab.view_laborder",
        ),
        name="lab_order_detail",
    ),
    path(
        "order/<int:order_id>/doctor-attachment/preview/",
        protected_view(
            views.lab_staff_doctor_attachment_file,
            "lab.view_laborder",
        ),
        {"inline": True},
        name="staff_doctor_attachment_preview",
    ),
    path(
        "order/<int:order_id>/doctor-attachment/download/",
        protected_view(
            views.lab_staff_doctor_attachment_file,
            "lab.view_laborder",
        ),
        {"inline": False},
        name="staff_doctor_attachment_download",
    ),
    path(
        "order/<int:order_id>/result-attachment/preview/",
        protected_view(
            views.lab_staff_result_attachment_file,
            "lab.view_labresult",
        ),
        {"inline": True},
        name="staff_result_attachment_preview",
    ),
    path(
        "order/<int:order_id>/result-attachment/download/",
        protected_view(
            views.lab_staff_result_attachment_file,
            "lab.view_labresult",
        ),
        {"inline": False},
        name="staff_result_attachment_download",
    ),
    path(
        "orders/<int:order_id>/",
        protected_view(
            views.lab_order_detail,
            "lab.view_laborder",
        ),
        name="lab_order_detail_alias",
    ),
]
