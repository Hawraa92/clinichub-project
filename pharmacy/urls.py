"""
URL configuration for the ClinicHub pharmacy module.

Every private pharmacy route is protected at the server level. Hiding a
button in a template is useful for the interface, but these checks are what
prevent a user from opening a restricted URL manually.
"""

from __future__ import annotations

from collections.abc import Callable
from functools import wraps
from typing import Any

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import HttpRequest, HttpResponseBase
from django.urls import path

from . import report_views, views


app_name = "pharmacy"


# -------------------------------------------------------------------------
# Permission helpers
# -------------------------------------------------------------------------
ViewFunction = Callable[..., HttpResponseBase]


def _require_all_permissions(
    view_function: ViewFunction,
    *permissions: str,
) -> ViewFunction:
    """
    Require authentication and every listed permission.

    Superusers always pass. Missing permissions raise PermissionDenied so
    ClinicHub's custom 403 page is displayed instead of silently redirecting.
    """

    @wraps(view_function)
    @login_required
    def wrapped_view(
        request: HttpRequest,
        *args: Any,
        **kwargs: Any,
    ) -> HttpResponseBase:
        user = request.user

        if user.is_superuser or user.has_perms(permissions):
            return view_function(request, *args, **kwargs)

        raise PermissionDenied

    return wrapped_view


def _require_any_permission(
    view_function: ViewFunction,
    *permissions: str,
) -> ViewFunction:
    """
    Require authentication and at least one listed permission.

    This is used for pages that combine several pharmacy functions, such as
    the dashboard and initial pharmacy setup.
    """

    @wraps(view_function)
    @login_required
    def wrapped_view(
        request: HttpRequest,
        *args: Any,
        **kwargs: Any,
    ) -> HttpResponseBase:
        user = request.user

        if user.is_superuser or any(
            user.has_perm(permission)
            for permission in permissions
        ):
            return view_function(request, *args, **kwargs)

        raise PermissionDenied

    return wrapped_view


# -------------------------------------------------------------------------
# Django permission names generated from pharmacy/models.py
# -------------------------------------------------------------------------
VIEW_PHARMACY = "pharmacy.view_pharmacy"
ADD_PHARMACY = "pharmacy.add_pharmacy"
CHANGE_PHARMACY = "pharmacy.change_pharmacy"

VIEW_ORDER = "pharmacy.view_pharmacyorder"
ADD_ORDER = "pharmacy.add_pharmacyorder"
CHANGE_ORDER = "pharmacy.change_pharmacyorder"
CHANGE_ORDER_ITEM = "pharmacy.change_pharmacyorderitem"

VIEW_DISPENSE = "pharmacy.view_dispense"
ADD_DISPENSE = "pharmacy.add_dispense"
CHANGE_DISPENSE = "pharmacy.change_dispense"
DELETE_DISPENSE = "pharmacy.delete_dispense"

VIEW_SALE = "pharmacy.view_pharmacysale"
ADD_SALE = "pharmacy.add_pharmacysale"
CHANGE_SALE = "pharmacy.change_pharmacysale"
DELETE_SALE = "pharmacy.delete_pharmacysale"

VIEW_INVENTORY = "pharmacy.view_pharmacyinventory"

VIEW_MEDICINE = "pharmacy.view_medicine"
ADD_MEDICINE = "pharmacy.add_medicine"
CHANGE_MEDICINE = "pharmacy.change_medicine"

VIEW_BATCH = "pharmacy.view_stockbatch"
ADD_BATCH = "pharmacy.add_stockbatch"

VIEW_MOVEMENT = "pharmacy.view_stockmovement"


# The dashboard is available when the user can access at least one pharmacy
# section. Role/assignment checks already present inside the view remain active.
pharmacy_dashboard = _require_any_permission(
    views.dashboard,
    VIEW_PHARMACY,
    VIEW_ORDER,
    VIEW_DISPENSE,
    VIEW_SALE,
    VIEW_INVENTORY,
    VIEW_MEDICINE,
    VIEW_BATCH,
    VIEW_MOVEMENT,
)


urlpatterns = [
    # =====================================================================
    # Pharmacy dashboard
    # =====================================================================
    path(
        "",
        pharmacy_dashboard,
        name="dashboard",
    ),

    # =====================================================================
    # Standalone pharmacy setup
    # Add is needed for first-time setup; change is enough for later updates.
    # =====================================================================
    path(
        "standalone/setup/",
        _require_any_permission(
            views.standalone_setup,
            ADD_PHARMACY,
            CHANGE_PHARMACY,
        ),
        name="standalone_setup",
    ),

    # =====================================================================
    # Prescription pharmacy orders
    # =====================================================================
    path(
        "orders/",
        _require_all_permissions(
            views.order_list,
            VIEW_ORDER,
        ),
        name="orders",
    ),
    path(
        "orders/<int:pk>/",
        _require_all_permissions(
            views.order_detail,
            VIEW_ORDER,
        ),
        name="order_detail",
    ),
    path(
        "orders/<int:pk>/accept/",
        _require_all_permissions(
            views.accept_order,
            CHANGE_ORDER,
        ),
        name="accept_order",
    ),
    path(
        "orders/<int:pk>/start/",
        _require_all_permissions(
            views.start_order,
            CHANGE_ORDER,
        ),
        name="start_order",
    ),
    path(
        "orders/<int:pk>/reject/",
        _require_all_permissions(
            views.reject_order,
            CHANGE_ORDER,
        ),
        name="reject_order",
    ),
    path(
        "orders/<int:pk>/cancel/",
        _require_all_permissions(
            views.cancel_order,
            CHANGE_ORDER,
        ),
        name="cancel_order",
    ),
    path(
        "orders/<int:pk>/dispense/",
        _require_all_permissions(
            views.dispense_order,
            VIEW_ORDER,
            CHANGE_ORDER,
            ADD_DISPENSE,
        ),
        name="dispense_order",
    ),
    path(
        "order-items/<int:item_id>/assign/",
        _require_all_permissions(
            views.assign_order_item,
            CHANGE_ORDER_ITEM,
        ),
        name="assign_order_item",
    ),

    # =====================================================================
    # Prescription dispensing, payment and receipt
    # Delete permission controls voiding because records remain in the audit
    # trail and are not physically removed.
    # =====================================================================
    path(
        "dispenses/<int:pk>/",
        _require_all_permissions(
            views.dispense_detail,
            VIEW_DISPENSE,
        ),
        name="dispense_detail",
    ),
    path(
        "dispenses/<int:pk>/receipt/",
        _require_all_permissions(
            views.dispense_receipt,
            VIEW_DISPENSE,
        ),
        name="dispense_receipt",
    ),
    path(
        "dispenses/<int:pk>/payment/",
        _require_all_permissions(
            views.record_payment,
            VIEW_DISPENSE,
            CHANGE_DISPENSE,
        ),
        name="record_payment",
    ),
    path(
        "dispenses/<int:pk>/void/",
        _require_all_permissions(
            views.void_dispense,
            VIEW_DISPENSE,
            DELETE_DISPENSE,
        ),
        name="void_dispense",
    ),

    # =====================================================================
    # Direct sales / Point of Sale (POS)
    # =====================================================================
    path(
        "sales/",
        _require_all_permissions(
            views.sale_list,
            VIEW_SALE,
        ),
        name="sales",
    ),
    path(
        "sales/new/",
        _require_all_permissions(
            views.sale_create,
            ADD_SALE,
        ),
        name="sale_create",
    ),
    path(
        "sales/<int:pk>/",
        _require_all_permissions(
            views.sale_detail,
            VIEW_SALE,
        ),
        name="sale_detail",
    ),
    path(
        "sales/<int:pk>/receipt/",
        _require_all_permissions(
            views.sale_receipt,
            VIEW_SALE,
        ),
        name="sale_receipt",
    ),
    path(
        "sales/<int:pk>/payment/",
        _require_all_permissions(
            views.sale_payment,
            VIEW_SALE,
            CHANGE_SALE,
        ),
        name="sale_payment",
    ),
    path(
        "sales/<int:pk>/void/",
        _require_all_permissions(
            views.sale_void,
            VIEW_SALE,
            DELETE_SALE,
        ),
        name="sale_void",
    ),

    # =====================================================================
    # Inventory and medicine management
    # =====================================================================
    path(
        "inventory/",
        _require_all_permissions(
            views.inventory_list,
            VIEW_INVENTORY,
        ),
        name="inventory",
    ),
    path(
        "medicines/",
        _require_all_permissions(
            views.medicine_list,
            VIEW_MEDICINE,
        ),
        name="medicines",
    ),
    path(
        "medicines/new/",
        _require_all_permissions(
            views.medicine_create,
            ADD_MEDICINE,
        ),
        name="medicine_create",
    ),
    path(
        "medicines/<int:pk>/edit/",
        _require_all_permissions(
            views.medicine_edit,
            CHANGE_MEDICINE,
        ),
        name="medicine_edit",
    ),
    path(
        "medicines/<int:pk>/toggle-active/",
        _require_all_permissions(
            views.medicine_toggle_active,
            CHANGE_MEDICINE,
        ),
        name="medicine_toggle_active",
    ),
    path(
        "batches/",
        _require_all_permissions(
            views.batch_list,
            VIEW_BATCH,
        ),
        name="batches",
    ),
    path(
        "batches/receive/",
        _require_all_permissions(
            views.receive_stock,
            ADD_BATCH,
        ),
        name="receive_stock",
    ),
    path(
        "movements/",
        _require_all_permissions(
            views.stock_movement_list,
            VIEW_MOVEMENT,
        ),
        name="movements",
    ),

    # =====================================================================
    # Pharmacy reports
    # The dashboard combines sales and inventory information, so both view
    # permissions are required. Each CSV export requires only its own data.
    # =====================================================================
    path(
        "reports/",
        _require_all_permissions(
            report_views.reports_dashboard,
            VIEW_SALE,
            VIEW_INVENTORY,
        ),
        name="reports",
    ),
    path(
        "reports/print/",
        _require_all_permissions(
            report_views.reports_print,
            VIEW_SALE,
            VIEW_INVENTORY,
        ),
        name="reports_print",
    ),
    path(
        "reports/sales.csv",
        _require_all_permissions(
            report_views.sales_report_csv,
            VIEW_SALE,
        ),
        name="sales_report_csv",
    ),
    path(
        "reports/inventory.csv",
        _require_all_permissions(
            report_views.inventory_report_csv,
            VIEW_INVENTORY,
        ),
        name="inventory_report_csv",
    ),

    # =====================================================================
    # Doctor sends a prescription to an integrated pharmacy
    # =====================================================================
    path(
        "prescriptions/<int:prescription_id>/send/",
        _require_all_permissions(
            views.send_prescription,
            ADD_ORDER,
        ),
        name="send_prescription",
    ),
]
