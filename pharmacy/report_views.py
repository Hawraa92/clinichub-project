from __future__ import annotations

import csv
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from django.db.models import (
    DecimalField,
    ExpressionWrapper,
    F,
    IntegerField,
    Q,
    Sum,
    Value,
)
from django.db.models.functions import Coalesce
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.utils import timezone
from django.utils.dateparse import parse_date

from .access import (
    accessible_pharmacies,
    active_pharmacy_assignments,
    is_platform_admin,
    pharmacy_portal_required,
)
from .models import (
    Dispense,
    DispenseItem,
    PharmacyInventory,
    PharmacySale,
    PharmacySaleAllocation,
    PharmacySaleItem,
    StockBatch,
)


MONEY_FIELD = DecimalField(max_digits=18, decimal_places=2)
ZERO_MONEY = Value(Decimal("0.00"), output_field=MONEY_FIELD)


def _money_sum(queryset, field_name: str) -> Decimal:
    result = queryset.aggregate(
        amount=Coalesce(
            Sum(field_name, output_field=MONEY_FIELD),
            ZERO_MONEY,
            output_field=MONEY_FIELD,
        ),
    )
    return result["amount"] or Decimal("0.00")


def _expression_sum(queryset, expression) -> Decimal:
    result = queryset.aggregate(
        amount=Coalesce(
            Sum(expression, output_field=MONEY_FIELD),
            ZERO_MONEY,
            output_field=MONEY_FIELD,
        ),
    )
    return result["amount"] or Decimal("0.00")


def _portal_context(request: HttpRequest) -> dict[str, Any]:
    assignments = list(active_pharmacy_assignments(request.user))
    return {
        "pharmacy_assignments": assignments,
        "is_pharmacy_staff": (
            bool(assignments)
            or accessible_pharmacies(request.user).exists()
        ),
        "is_platform_admin": is_platform_admin(request.user),
    }


def _report_period(request: HttpRequest) -> tuple[date, date]:
    today = timezone.localdate()
    default_start = today - timedelta(days=29)

    date_from = parse_date((request.GET.get("date_from") or "").strip())
    date_to = parse_date((request.GET.get("date_to") or "").strip())

    date_from = date_from or default_start
    date_to = date_to or today

    if date_from > date_to:
        date_from, date_to = date_to, date_from

    return date_from, date_to


def _selected_pharmacies(request: HttpRequest):
    pharmacies = accessible_pharmacies(request.user)
    pharmacy_id = (request.GET.get("pharmacy") or "").strip()

    if pharmacy_id.isdigit() and pharmacies.filter(pk=int(pharmacy_id)).exists():
        selected = pharmacies.filter(pk=int(pharmacy_id))
    else:
        pharmacy_id = ""
        selected = pharmacies

    return pharmacies, selected, pharmacy_id


def _medicine_name(values: dict[str, Any]) -> str:
    return " ".join(
        value
        for value in (
            values.get("medicine__brand_name")
            or values.get("medicine__generic_name")
            or "Medicine",
            values.get("medicine__strength") or "",
        )
        if value
    ).strip()


def _top_medicines(sales, dispenses) -> list[dict[str, Any]]:
    direct_line_total = ExpressionWrapper(
        (F("quantity") * F("unit_price")) - F("discount_amount"),
        output_field=MONEY_FIELD,
    )
    dispense_line_total = ExpressionWrapper(
        F("quantity") * F("unit_price"),
        output_field=MONEY_FIELD,
    )

    direct_rows = (
        PharmacySaleItem.objects.filter(sale__in=sales)
        .values(
            "medicine_id",
            "medicine__generic_name",
            "medicine__brand_name",
            "medicine__strength",
        )
        .annotate(
            sold_quantity=Coalesce(
                Sum("quantity"),
                Value(0),
                output_field=IntegerField(),
            ),
            revenue=Coalesce(
                Sum(direct_line_total),
                ZERO_MONEY,
                output_field=MONEY_FIELD,
            ),
        )
    )

    dispense_rows = (
        DispenseItem.objects.filter(dispense__in=dispenses)
        .values(
            "stock_batch__inventory__medicine_id",
            "stock_batch__inventory__medicine__generic_name",
            "stock_batch__inventory__medicine__brand_name",
            "stock_batch__inventory__medicine__strength",
        )
        .annotate(
            sold_quantity=Coalesce(
                Sum("quantity"),
                Value(0),
                output_field=IntegerField(),
            ),
            revenue=Coalesce(
                Sum(dispense_line_total),
                ZERO_MONEY,
                output_field=MONEY_FIELD,
            ),
        )
    )

    totals: dict[int, dict[str, Any]] = defaultdict(
        lambda: {
            "medicine": "",
            "quantity": 0,
            "revenue": Decimal("0.00"),
        },
    )

    for row in direct_rows:
        medicine_id = row["medicine_id"]
        totals[medicine_id]["medicine"] = _medicine_name(row)
        totals[medicine_id]["quantity"] += int(row["sold_quantity"] or 0)
        totals[medicine_id]["revenue"] += row["revenue"] or Decimal("0.00")

    for row in dispense_rows:
        medicine_id = row["stock_batch__inventory__medicine_id"]
        normalized = {
            "medicine__generic_name": row[
                "stock_batch__inventory__medicine__generic_name"
            ],
            "medicine__brand_name": row[
                "stock_batch__inventory__medicine__brand_name"
            ],
            "medicine__strength": row[
                "stock_batch__inventory__medicine__strength"
            ],
        }
        totals[medicine_id]["medicine"] = _medicine_name(normalized)
        totals[medicine_id]["quantity"] += int(row["sold_quantity"] or 0)
        totals[medicine_id]["revenue"] += row["revenue"] or Decimal("0.00")

    return sorted(
        totals.values(),
        key=lambda item: (item["quantity"], item["revenue"]),
        reverse=True,
    )[:10]


def _report_data(request: HttpRequest) -> dict[str, Any]:
    pharmacies, selected_pharmacies, pharmacy_id = _selected_pharmacies(request)
    pharmacy_ids = selected_pharmacies.values_list("pk", flat=True)
    date_from, date_to = _report_period(request)

    sales = (
        PharmacySale.objects.filter(
            pharmacy_id__in=pharmacy_ids,
            status=PharmacySale.Status.COMPLETED,
            completed_at__date__gte=date_from,
            completed_at__date__lte=date_to,
        )
        .select_related("pharmacy", "cashier__staff_assignment__user")
        .order_by("-completed_at", "-id")
    )

    dispenses = (
        Dispense.objects.filter(
            order__pharmacy_id__in=pharmacy_ids,
            status=Dispense.Status.COMPLETED,
            dispensed_at__date__gte=date_from,
            dispensed_at__date__lte=date_to,
        )
        .select_related(
            "order",
            "order__pharmacy",
            "order__prescription",
            "order__prescription__patient",
            "dispensed_by__staff_assignment__user",
        )
        .order_by("-dispensed_at", "-id")
    )

    direct_revenue = _money_sum(sales, "total_amount")
    prescription_revenue = _money_sum(dispenses, "total_amount")
    direct_collected = _money_sum(sales, "amount_paid")
    prescription_collected = _money_sum(dispenses, "amount_paid")

    direct_cost_expression = ExpressionWrapper(
        F("quantity") * F("unit_purchase_price"),
        output_field=MONEY_FIELD,
    )
    prescription_cost_expression = ExpressionWrapper(
        F("quantity") * F("stock_batch__purchase_price"),
        output_field=MONEY_FIELD,
    )

    direct_cost = _expression_sum(
        PharmacySaleAllocation.objects.filter(
            sale_item__sale__in=sales,
        ),
        direct_cost_expression,
    )
    prescription_cost = _expression_sum(
        DispenseItem.objects.filter(dispense__in=dispenses),
        prescription_cost_expression,
    )

    total_revenue = direct_revenue + prescription_revenue
    total_collected = direct_collected + prescription_collected
    total_cost = direct_cost + prescription_cost
    outstanding = max(
        total_revenue - total_collected,
        Decimal("0.00"),
    )
    gross_profit = total_revenue - total_cost

    today = timezone.localdate()
    expiry_limit = today + timedelta(days=90)

    inventory = (
        PharmacyInventory.objects.filter(
            pharmacy_id__in=pharmacy_ids,
            is_active=True,
        )
        .select_related("pharmacy", "medicine")
        .annotate(
            available_quantity=Coalesce(
                Sum(
                    "batches__quantity_on_hand",
                    filter=Q(
                        batches__is_active=True,
                        batches__is_deleted=False,
                        batches__expiry_date__gte=today,
                    ),
                ),
                Value(0),
                output_field=IntegerField(),
            ),
        )
        .order_by("pharmacy__name", "medicine__generic_name")
    )

    low_stock = inventory.filter(
        available_quantity__lte=F("reorder_level"),
    )[:20]

    expiring_batches = (
        StockBatch.objects.filter(
            inventory__pharmacy_id__in=pharmacy_ids,
            is_active=True,
            quantity_on_hand__gt=0,
            expiry_date__gte=today,
            expiry_date__lte=expiry_limit,
        )
        .select_related(
            "inventory",
            "inventory__pharmacy",
            "inventory__medicine",
        )
        .order_by("expiry_date", "inventory__pharmacy__name")[:20]
    )

    stock_value_expression = ExpressionWrapper(
        F("quantity_on_hand") * F("purchase_price"),
        output_field=MONEY_FIELD,
    )
    stock_value = _expression_sum(
        StockBatch.objects.filter(
            inventory__pharmacy_id__in=pharmacy_ids,
            is_active=True,
            quantity_on_hand__gt=0,
            expiry_date__gte=today,
        ),
        stock_value_expression,
    )

    unpaid_sales = sales.filter(
        payment_status__in=[
            PharmacySale.PaymentStatus.UNPAID,
            PharmacySale.PaymentStatus.PARTIALLY_PAID,
        ],
    )[:10]
    unpaid_dispenses = dispenses.filter(
        payment_status__in=[
            Dispense.PaymentStatus.UNPAID,
            Dispense.PaymentStatus.PARTIALLY_PAID,
        ],
    )[:10]

    return {
        **_portal_context(request),
        "pharmacies": pharmacies,
        "selected_pharmacies": selected_pharmacies,
        "filters": {
            "date_from": date_from,
            "date_to": date_to,
            "pharmacy": pharmacy_id,
        },
        "sales": sales,
        "dispenses": dispenses,
        "summary": {
            "direct_sale_count": sales.count(),
            "prescription_count": dispenses.count(),
            "transaction_count": sales.count() + dispenses.count(),
            "direct_revenue": direct_revenue,
            "prescription_revenue": prescription_revenue,
            "total_revenue": total_revenue,
            "total_collected": total_collected,
            "outstanding": outstanding,
            "total_cost": total_cost,
            "gross_profit": gross_profit,
            "stock_value": stock_value,
        },
        "top_medicines": _top_medicines(sales, dispenses),
        "low_stock": low_stock,
        "expiring_batches": expiring_batches,
        "unpaid_sales": unpaid_sales,
        "unpaid_dispenses": unpaid_dispenses,
        "inventory_count": inventory.count(),
    }


@pharmacy_portal_required
def reports_dashboard(request: HttpRequest) -> HttpResponse:
    return render(
        request,
        "pharmacy/reports_dashboard.html",
        _report_data(request),
    )


@pharmacy_portal_required
def reports_print(request: HttpRequest) -> HttpResponse:
    context = _report_data(request)
    context["printed_at"] = timezone.now()
    return render(
        request,
        "pharmacy/reports_print.html",
        context,
    )


@pharmacy_portal_required
def sales_report_csv(request: HttpRequest) -> HttpResponse:
    data = _report_data(request)
    date_from = data["filters"]["date_from"]
    date_to = data["filters"]["date_to"]

    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = (
        f'attachment; filename="pharmacy-sales-{date_from}-{date_to}.csv"'
    )
    response.write("\ufeff")
    writer = csv.writer(response)
    writer.writerow(
        [
            "Source",
            "Reference",
            "Pharmacy",
            "Customer / Patient",
            "Date",
            "Total (IQD)",
            "Paid (IQD)",
            "Balance (IQD)",
            "Payment status",
            "Payment method",
        ],
    )

    for sale in data["sales"]:
        writer.writerow(
            [
                "Direct sale",
                sale.sale_number,
                sale.pharmacy.name,
                sale.customer_name or "Walk-in customer",
                timezone.localtime(sale.completed_at).strftime("%Y-%m-%d %H:%M"),
                sale.total_amount,
                sale.amount_paid,
                sale.balance_due,
                sale.get_payment_status_display(),
                sale.get_payment_method_display() if sale.payment_method else "",
            ],
        )

    for dispense in data["dispenses"]:
        prescription = dispense.order.prescription
        writer.writerow(
            [
                "Prescription",
                dispense.receipt_number,
                dispense.order.pharmacy.name,
                getattr(prescription.patient, "full_name", str(prescription.patient)),
                timezone.localtime(dispense.dispensed_at).strftime(
                    "%Y-%m-%d %H:%M",
                ),
                dispense.total_amount,
                dispense.amount_paid,
                dispense.balance_due,
                dispense.get_payment_status_display(),
                (
                    dispense.get_payment_method_display()
                    if dispense.payment_method
                    else ""
                ),
            ],
        )

    writer.writerow([])
    writer.writerow(["Summary"])
    writer.writerow(["Total revenue", data["summary"]["total_revenue"]])
    writer.writerow(["Collected", data["summary"]["total_collected"]])
    writer.writerow(["Outstanding", data["summary"]["outstanding"]])
    writer.writerow(["Estimated cost", data["summary"]["total_cost"]])
    writer.writerow(["Estimated gross profit", data["summary"]["gross_profit"]])
    return response


@pharmacy_portal_required
def inventory_report_csv(request: HttpRequest) -> HttpResponse:
    pharmacies, selected_pharmacies, _pharmacy_id = _selected_pharmacies(request)
    del pharmacies
    pharmacy_ids = selected_pharmacies.values_list("pk", flat=True)
    today = timezone.localdate()

    inventory = (
        PharmacyInventory.objects.filter(
            pharmacy_id__in=pharmacy_ids,
        )
        .select_related("pharmacy", "medicine")
        .annotate(
            available_quantity=Coalesce(
                Sum(
                    "batches__quantity_on_hand",
                    filter=Q(
                        batches__is_active=True,
                        batches__is_deleted=False,
                        batches__expiry_date__gte=today,
                    ),
                ),
                Value(0),
                output_field=IntegerField(),
            ),
        )
        .order_by("pharmacy__name", "medicine__generic_name")
    )

    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = (
        f'attachment; filename="pharmacy-inventory-{today}.csv"'
    )
    response.write("\ufeff")
    writer = csv.writer(response)
    writer.writerow(
        [
            "Pharmacy",
            "Medicine",
            "Code",
            "Available",
            "Reorder level",
            "Target stock",
            "Status",
        ],
    )

    for item in inventory:
        if item.available_quantity <= 0:
            status = "Out of stock"
        elif item.available_quantity <= item.reorder_level:
            status = "Low stock"
        else:
            status = "Available"

        writer.writerow(
            [
                item.pharmacy.name,
                item.medicine.display_name,
                item.medicine.code,
                item.available_quantity,
                item.reorder_level,
                item.target_stock,
                status,
            ],
        )

    return response
