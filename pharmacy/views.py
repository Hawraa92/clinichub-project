from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from typing import Any, Iterable

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.db import IntegrityError, transaction
from django.db.models import Count, F, IntegerField, Q, Sum, Value
from django.db.models.functions import Coalesce
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST, require_http_methods

from prescription.models import Prescription

from .access import (
    accessible_pharmacies,
    active_pharmacy_assignments,
    assignment_for_order,
    is_platform_admin,
    pharmacy_portal_required,
    user_can_manage_prescription,
    user_can_view_order,
)
from .forms import (
    AssignMedicineForm,
    DirectSaleForm,
    DirectSaleItemFormSet,
    DirectSalePaymentForm,
    DispenseOrderForm,
    MedicineManagementForm,
    RecordPaymentForm,
    RejectOrderForm,
    SendPrescriptionToPharmacyForm,
    StandalonePharmacySetupForm,
    StockReceiptForm,
    VoidDirectSaleForm,
    VoidDispenseForm,
)
from .models import (
    Dispense,
    DispenseItem,
    Medicine,
    Pharmacy,
    PharmacyInventory,
    PharmacyOrder,
    PharmacyOrderItem,
    PharmacySale,
    PharmacyStaffAssignment,
    StockBatch,
    StockMovement,
)
from .services import (
    accept_pharmacy_order,
    assign_medicine_to_order_item,
    cancel_pharmacy_order,
    complete_order_dispense,
    create_direct_sale,
    record_direct_sale_payment,
    reject_pharmacy_order,
    send_prescription_to_pharmacy,
    start_pharmacy_order,
    void_completed_dispense,
    void_direct_sale,
)


PAGE_SIZE = 20


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------
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


def _context(request: HttpRequest, **extra: Any) -> dict[str, Any]:
    context = _portal_context(request)
    context.update(extra)
    return context


def _validation_messages(error: ValidationError) -> list[str]:
    if hasattr(error, "message_dict"):
        output: list[str] = []
        for values in error.message_dict.values():
            if isinstance(values, (list, tuple)):
                output.extend(str(value) for value in values)
            else:
                output.append(str(values))
        return output
    if hasattr(error, "messages"):
        return [str(value) for value in error.messages]
    return [str(error)]


def _add_validation_to_form(form, error: ValidationError) -> None:
    if hasattr(error, "message_dict"):
        for field_name, values in error.message_dict.items():
            target = field_name if field_name in form.fields else None
            if not isinstance(values, (list, tuple)):
                values = [values]
            for value in values:
                form.add_error(target, str(value))
        return

    for value in _validation_messages(error):
        form.add_error(None, value)


def _add_validation_to_formset(formset, error: ValidationError) -> None:
    values = _validation_messages(error)
    formset._non_form_errors = formset.error_class(values)


def _flash_validation_error(request: HttpRequest, error: ValidationError) -> None:
    for value in _validation_messages(error):
        messages.error(request, value)


def _selected_accessible_pharmacy(
    request: HttpRequest,
    value: str | int | None,
) -> Pharmacy | None:
    if value in {None, ""}:
        return None
    try:
        pharmacy_id = int(value)
    except (TypeError, ValueError):
        return None
    return accessible_pharmacies(request.user).filter(pk=pharmacy_id).first()


def _assignment_for_pharmacy(
    user: Any,
    pharmacy: Pharmacy | int,
    *,
    manager_only: bool = False,
) -> PharmacyStaffAssignment:
    pharmacy_id = pharmacy.pk if isinstance(pharmacy, Pharmacy) else int(pharmacy)
    assignments = active_pharmacy_assignments(user).filter(pharmacy_id=pharmacy_id)
    if manager_only:
        assignments = assignments.filter(is_manager=True)
    assignment = assignments.order_by("-is_manager", "id").first()
    if assignment is None:
        if manager_only:
            raise PermissionDenied("An active pharmacy manager assignment is required.")
        raise PermissionDenied("You are not assigned to this pharmacy.")
    return assignment


def _manageable_pharmacies(user: Any):
    pharmacies = accessible_pharmacies(user)
    if (
        is_platform_admin(user)
        or (
            getattr(user, "role", None) == "admin"
            and pharmacies.exists()
        )
    ):
        return pharmacies
    manager_ids = active_pharmacy_assignments(user).filter(
        is_manager=True,
    ).values_list("pharmacy_id", flat=True)
    return pharmacies.filter(pk__in=manager_ids)


def _accessible_order_queryset(user: Any):
    return PharmacyOrder.objects.filter(
        pharmacy__in=accessible_pharmacies(user),
    )


def _accessible_dispense_queryset(user: Any):
    return Dispense.objects.filter(
        order__pharmacy__in=accessible_pharmacies(user),
    )


def _accessible_sale_queryset(user: Any):
    return PharmacySale.objects.filter(
        pharmacy__in=accessible_pharmacies(user),
    )


def _available_inventory_queryset(user: Any):
    today = timezone.localdate()
    return (
        PharmacyInventory.objects.filter(
            pharmacy__in=accessible_pharmacies(user),
            is_active=True,
            medicine__is_deleted=False,
            pharmacy__is_active=True,
        )
        .select_related(
            "pharmacy",
            "pharmacy__branch",
            "pharmacy__branch__hospital",
            "medicine",
        )
        .annotate(
            available_quantity=Coalesce(
                Sum(
                    "batches__quantity_on_hand",
                    filter=Q(
                        batches__is_active=True,
                        batches__is_deleted=False,
                        batches__quantity_on_hand__gt=0,
                        batches__expiry_date__gte=today,
                    ),
                ),
                Value(0),
                output_field=IntegerField(),
            )
        )
    )


def _paginate(request: HttpRequest, queryset, per_page: int = PAGE_SIZE):
    return Paginator(queryset, per_page).get_page(request.GET.get("page"))


def _payment_note(existing: str, *, amount: Decimal, user: Any, note: str = "") -> str:
    stamp = timezone.localtime().strftime("%Y-%m-%d %H:%M")
    line = f"Payment {amount:.2f} recorded by {user} at {stamp}."
    clean_note = (note or "").strip()
    if clean_note:
        line = f"{line} {clean_note}"
    return f"{existing or ''}\n{line}".strip()


# ---------------------------------------------------------------------------
# Dashboard and standalone setup
# ---------------------------------------------------------------------------
@pharmacy_portal_required
@require_GET
def dashboard(request: HttpRequest) -> HttpResponse:
    pharmacies = list(accessible_pharmacies(request.user))
    pharmacy_ids = [pharmacy.pk for pharmacy in pharmacies]

    stats = {
        "sent": 0,
        "accepted": 0,
        "in_progress": 0,
        "dispensed": 0,
        "urgent": 0,
    }
    recent_orders = PharmacyOrder.objects.none()

    if request.user.has_perm("pharmacy.view_pharmacyorder"):
        orders = PharmacyOrder.objects.filter(pharmacy_id__in=pharmacy_ids)
        grouped = {
            row["status"]: row["count"]
            for row in orders.values("status").annotate(count=Count("id"))
        }
        stats.update(
            {
                "sent": grouped.get(PharmacyOrder.Status.SENT, 0),
                "accepted": grouped.get(PharmacyOrder.Status.ACCEPTED, 0),
                "in_progress": grouped.get(PharmacyOrder.Status.IN_PROGRESS, 0),
                "dispensed": grouped.get(PharmacyOrder.Status.DISPENSED, 0),
                "urgent": orders.filter(
                    priority__in=[
                        PharmacyOrder.Priority.URGENT,
                        PharmacyOrder.Priority.STAT,
                    ]
                ).count(),
            }
        )
        recent_orders = (
            orders.select_related(
                "pharmacy",
                "prescription",
                "prescription__doctor__user",
            )
            .order_by("-sent_at", "-pk")[:10]
        )

    low_stock = PharmacyInventory.objects.none()
    if request.user.has_perm("pharmacy.view_pharmacyinventory"):
        low_stock = (
            _available_inventory_queryset(request.user)
            .filter(available_quantity__lte=F("reorder_level"))
            .order_by("available_quantity", "medicine__generic_name")[:10]
        )

    return render(
        request,
        "pharmacy/dashboard.html",
        _context(
            request,
            pharmacies=pharmacies,
            stats=stats,
            recent_orders=recent_orders,
            low_stock=low_stock,
        ),
    )


@pharmacy_portal_required
@require_http_methods(["GET", "POST"])
def standalone_setup(request: HttpRequest) -> HttpResponse:
    existing_assignment = (
        active_pharmacy_assignments(request.user)
        .filter(
            is_manager=True,
            pharmacy__operating_mode=Pharmacy.OperatingModes.STANDALONE,
        )
        .select_related(
            "pharmacy",
            "pharmacy__branch",
            "pharmacy__branch__hospital",
        )
        .first()
    )
    existing = existing_assignment.pharmacy if existing_assignment else None

    initial: dict[str, Any] = {}
    if existing:
        initial = {
            "name": existing.name,
            "code": existing.code,
            "phone": existing.phone,
            "email": existing.email,
            "address": existing.location or existing.branch.address,
            "license_number": existing.license_number,
        }

    form = StandalonePharmacySetupForm(
        request.POST if request.method == "POST" else None,
        initial=initial,
    )

    if request.method == "POST" and form.is_valid():
        try:
            if existing is None:
                pharmacy, _assignment = form.save(owner_user=request.user)
                messages.success(request, f"Standalone pharmacy {pharmacy.name} was created.")
            else:
                with transaction.atomic():
                    pharmacy = Pharmacy.objects.select_for_update().select_related(
                        "branch",
                        "branch__hospital",
                    ).get(pk=existing.pk)
                    branch = pharmacy.branch
                    hospital = branch.hospital
                    clean = form.cleaned_data
                    organization_code = f"ST-{clean['code']}"

                    if (
                        hospital.__class__.all_objects.filter(code=organization_code)
                        .exclude(pk=hospital.pk)
                        .exists()
                    ):
                        form.add_error("code", "A standalone pharmacy with this code already exists.")
                        raise ValidationError("Duplicate standalone pharmacy code.")

                    hospital.name = f"{clean['name']} Organization"
                    hospital.code = organization_code
                    hospital.phone = clean.get("phone", "")
                    hospital.email = clean.get("email", "")
                    hospital.address = clean.get("address", "")
                    hospital.save()

                    branch.phone = clean.get("phone", "")
                    branch.email = clean.get("email", "")
                    branch.address = clean.get("address", "")
                    branch.save()

                    pharmacy.name = clean["name"]
                    pharmacy.code = clean["code"]
                    pharmacy.phone = clean.get("phone", "")
                    pharmacy.email = clean.get("email", "")
                    pharmacy.location = clean.get("address", "")
                    pharmacy.license_number = clean.get("license_number", "")
                    pharmacy.save()

                messages.success(request, "Standalone pharmacy settings were updated.")

            return redirect("pharmacy:dashboard")
        except ValidationError as error:
            if not form.errors:
                _add_validation_to_form(form, error)
        except IntegrityError:
            form.add_error(None, "The pharmacy could not be saved because the name or code already exists.")

    return render(
        request,
        "pharmacy/standalone_setup.html",
        _context(
            request,
            form=form,
            page_title=(
                "Update standalone pharmacy"
                if existing
                else "Create standalone pharmacy"
            ),
            submit_label="Save pharmacy",
            cancel_url=reverse("pharmacy:dashboard"),
            existing_pharmacy=existing,
        ),
    )


# ---------------------------------------------------------------------------
# Prescription orders
# ---------------------------------------------------------------------------
@pharmacy_portal_required
@require_GET
def order_list(request: HttpRequest) -> HttpResponse:
    pharmacies = accessible_pharmacies(request.user)
    queryset = (
        PharmacyOrder.objects.filter(pharmacy__in=pharmacies)
        .select_related(
            "pharmacy",
            "pharmacy__branch",
            "pharmacy__branch__hospital",
            "prescription",
            "prescription__doctor__user",
            "assigned_to",
            "assigned_to__staff_assignment__user",
        )
        .order_by("-sent_at", "-pk")
    )

    filters = {
        "q": (request.GET.get("q") or "").strip(),
        "status": (request.GET.get("status") or "").strip(),
        "priority": (request.GET.get("priority") or "").strip(),
        "pharmacy": (request.GET.get("pharmacy") or "").strip(),
    }

    if filters["q"]:
        q = filters["q"]
        search = (
            Q(prescription__patient_full_name__icontains=q)
            | Q(prescription__diagnosis__icontains=q)
            | Q(prescription__doctor__user__first_name__icontains=q)
            | Q(prescription__doctor__user__last_name__icontains=q)
            | Q(prescription__doctor__user__email__icontains=q)
        )
        if q.isdigit():
            search |= Q(pk=int(q)) | Q(prescription_id=int(q))
        queryset = queryset.filter(search)

    valid_statuses = {value for value, _label in PharmacyOrder.Status.choices}
    if filters["status"] in valid_statuses:
        queryset = queryset.filter(status=filters["status"])

    valid_priorities = {value for value, _label in PharmacyOrder.Priority.choices}
    if filters["priority"] in valid_priorities:
        queryset = queryset.filter(priority=filters["priority"])

    selected = _selected_accessible_pharmacy(request, filters["pharmacy"])
    if selected:
        queryset = queryset.filter(pharmacy=selected)
    elif filters["pharmacy"]:
        filters["pharmacy"] = ""

    return render(
        request,
        "pharmacy/order_list.html",
        _context(
            request,
            page_obj=_paginate(request, queryset),
            pharmacies=pharmacies,
            status_choices=PharmacyOrder.Status.choices,
            priority_choices=PharmacyOrder.Priority.choices,
            filters=filters,
        ),
    )


@login_required
@require_GET
def order_detail(request: HttpRequest, pk: int) -> HttpResponse:
    order = get_object_or_404(
        PharmacyOrder.objects.select_related(
            "pharmacy",
            "pharmacy__branch",
            "pharmacy__branch__hospital",
            "prescription",
            "prescription__doctor__user",
            "prescription__patient",
            "assigned_to",
            "assigned_to__staff_assignment__user",
        ).prefetch_related(
            "items__medicine",
            "dispenses__dispensed_by__staff_assignment__user",
        ),
        pk=pk,
    )

    if not user_can_view_order(request.user, order):
        raise PermissionDenied("You do not have access to this pharmacy order.")

    current_assignment = assignment_for_order(request.user, order)
    processable = {
        PharmacyOrder.Status.SENT,
        PharmacyOrder.Status.ACCEPTED,
        PharmacyOrder.Status.IN_PROGRESS,
        PharmacyOrder.Status.PARTIALLY_DISPENSED,
    }
    can_process = bool(
        current_assignment
        and order.status in processable
        and request.user.has_perm("pharmacy.change_pharmacyorder")
    )
    can_cancel = bool(
        user_can_manage_prescription(request.user, order.prescription)
        and order.status
        in {
            PharmacyOrder.Status.SENT,
            PharmacyOrder.Status.ACCEPTED,
            PharmacyOrder.Status.IN_PROGRESS,
        }
        and not order.dispenses.filter(status=Dispense.Status.COMPLETED).exists()
        and request.user.has_perm("pharmacy.change_pharmacyorder")
    )

    return render(
        request,
        "pharmacy/order_detail.html",
        _context(
            request,
            order=order,
            order_items=list(order.items.all().order_by("id")),
            dispenses=list(order.dispenses.all().order_by("-created_at", "-pk")),
            current_assignment=current_assignment,
            can_process=can_process,
            can_cancel=can_cancel,
        ),
    )


@pharmacy_portal_required
@require_POST
def accept_order(request: HttpRequest, pk: int) -> HttpResponse:
    order = get_object_or_404(_accessible_order_queryset(request.user), pk=pk)
    assignment = _assignment_for_pharmacy(request.user, order.pharmacy_id)
    try:
        accept_pharmacy_order(order=order, pharmacist_assignment=assignment)
        messages.success(request, "The pharmacy order was accepted.")
    except ValidationError as error:
        _flash_validation_error(request, error)
    return redirect("pharmacy:order_detail", pk=order.pk)


@pharmacy_portal_required
@require_POST
def start_order(request: HttpRequest, pk: int) -> HttpResponse:
    order = get_object_or_404(_accessible_order_queryset(request.user), pk=pk)
    assignment = _assignment_for_pharmacy(request.user, order.pharmacy_id)
    try:
        start_pharmacy_order(order=order, pharmacist_assignment=assignment)
        messages.success(request, "Order processing has started.")
    except ValidationError as error:
        _flash_validation_error(request, error)
    return redirect("pharmacy:order_detail", pk=order.pk)


@pharmacy_portal_required
@require_http_methods(["GET", "POST"])
def reject_order(request: HttpRequest, pk: int) -> HttpResponse:
    order = get_object_or_404(_accessible_order_queryset(request.user), pk=pk)
    assignment = _assignment_for_pharmacy(request.user, order.pharmacy_id)
    form = RejectOrderForm(request.POST if request.method == "POST" else None)

    if request.method == "POST" and form.is_valid():
        try:
            reject_pharmacy_order(
                order=order,
                pharmacist_assignment=assignment,
                reason=form.cleaned_data["reason"],
            )
            messages.success(request, "The pharmacy order was rejected.")
            return redirect("pharmacy:order_detail", pk=order.pk)
        except ValidationError as error:
            _add_validation_to_form(form, error)

    return render(
        request,
        "pharmacy/action_form.html",
        _context(
            request,
            form=form,
            order=order,
            page_title=f"Reject order #{order.pk}",
            submit_label="Reject order",
            danger_action=True,
            cancel_url=reverse("pharmacy:order_detail", kwargs={"pk": order.pk}),
        ),
    )


@login_required
@require_POST
def cancel_order(request: HttpRequest, pk: int) -> HttpResponse:
    order = get_object_or_404(PharmacyOrder.objects.select_related("prescription__doctor__user"), pk=pk)
    if not user_can_manage_prescription(request.user, order.prescription):
        raise PermissionDenied("Only the prescribing doctor or an administrator can cancel this order.")
    try:
        cancel_pharmacy_order(order=order, cancelled_by=request.user)
        messages.success(request, "The pharmacy order was cancelled.")
    except ValidationError as error:
        _flash_validation_error(request, error)
    return redirect("pharmacy:order_detail", pk=order.pk)


@pharmacy_portal_required
@require_http_methods(["GET", "POST"])
def assign_order_item(request: HttpRequest, item_id: int) -> HttpResponse:
    item = get_object_or_404(
        PharmacyOrderItem.objects.select_related(
            "order",
            "order__pharmacy",
            "order__pharmacy__branch",
            "medicine",
        ).filter(order__pharmacy__in=accessible_pharmacies(request.user)),
        pk=item_id,
    )
    assignment = _assignment_for_pharmacy(request.user, item.order.pharmacy_id)
    form = AssignMedicineForm(
        request.POST if request.method == "POST" else None,
        order_item=item,
    )

    if request.method == "POST" and form.is_valid():
        try:
            with transaction.atomic():
                updated = assign_medicine_to_order_item(
                    order_item=item,
                    medicine=form.cleaned_data["medicine"],
                    pharmacist_assignment=assignment,
                    is_substitution=form.cleaned_data.get("is_substitution", False),
                    notes=form.cleaned_data.get("notes", ""),
                )
                updated.requested_quantity = form.cleaned_data["requested_quantity"]
                updated.requested_unit = form.cleaned_data["requested_unit"]
                updated.save()
            messages.success(request, "The medicine was assigned to the order item.")
            return redirect("pharmacy:order_detail", pk=item.order_id)
        except ValidationError as error:
            _add_validation_to_form(form, error)

    return render(
        request,
        "pharmacy/action_form.html",
        _context(
            request,
            form=form,
            order=item.order,
            order_item=item,
            page_title=f"Assign medicine to {item.medication_name}",
            submit_label="Save assignment",
            cancel_url=reverse("pharmacy:order_detail", kwargs={"pk": item.order_id}),
        ),
    )


@pharmacy_portal_required
@require_http_methods(["GET", "POST"])
def dispense_order(request: HttpRequest, pk: int) -> HttpResponse:
    order = get_object_or_404(
        _accessible_order_queryset(request.user).select_related(
            "pharmacy",
            "prescription",
            "prescription__patient",
        ).prefetch_related("items__medicine"),
        pk=pk,
    )
    assignment = _assignment_for_pharmacy(request.user, order.pharmacy_id)
    form = DispenseOrderForm(
        request.POST if request.method == "POST" else None,
        order=order,
    )

    if request.method == "POST" and form.is_valid():
        try:
            with transaction.atomic():
                dispense = complete_order_dispense(
                    order=order,
                    pharmacist_assignment=assignment,
                    allocations=form.allocations(),
                    notes=form.cleaned_data.get("notes", ""),
                )
                payment = form.payment_data()
                dispense.total_amount = payment["total_amount"]
                dispense.amount_paid = payment["amount_paid"]
                dispense.payment_status = payment["payment_status"]
                dispense.payment_method = payment["payment_method"]
                dispense.transaction_reference = payment["transaction_reference"]
                dispense.received_by_name = payment["received_by_name"]
                dispense.notes = payment["notes"]
                dispense.save()
            messages.success(request, "The selected medicines were dispensed successfully.")
            return redirect("pharmacy:dispense_receipt", pk=dispense.pk)
        except ValidationError as error:
            _add_validation_to_form(form, error)

    return render(
        request,
        "pharmacy/dispense_form.html",
        _context(
            request,
            form=form,
            order=order,
            page_title=f"Dispense order #{order.pk}",
            submit_label="Complete dispense",
            cancel_url=reverse("pharmacy:order_detail", kwargs={"pk": order.pk}),
        ),
    )


# ---------------------------------------------------------------------------
# Dispensing records, receipts and payments
# ---------------------------------------------------------------------------
@pharmacy_portal_required
@require_GET
def dispense_detail(request: HttpRequest, pk: int) -> HttpResponse:
    dispense = get_object_or_404(
        _accessible_dispense_queryset(request.user).select_related(
            "order",
            "order__pharmacy",
            "order__prescription",
            "dispensed_by",
            "dispensed_by__staff_assignment__user",
        ).prefetch_related(
            "items__order_item",
            "items__stock_batch__inventory__medicine",
        ),
        pk=pk,
    )
    current_assignment = None
    if request.user.has_perm("pharmacy.delete_dispense"):
        current_assignment = (
            active_pharmacy_assignments(request.user)
            .filter(pharmacy_id=dispense.order.pharmacy_id)
            .order_by("-is_manager", "id")
            .first()
        )
    return render(
        request,
        "pharmacy/dispense_detail.html",
        _context(
            request,
            dispense=dispense,
            dispense_items=list(dispense.items.all().order_by("id")),
            current_assignment=current_assignment,
        ),
    )


@pharmacy_portal_required
@require_GET
def dispense_receipt(request: HttpRequest, pk: int) -> HttpResponse:
    dispense = get_object_or_404(
        _accessible_dispense_queryset(request.user).select_related(
            "order",
            "order__pharmacy",
            "order__pharmacy__branch",
            "order__pharmacy__branch__hospital",
            "order__prescription",
            "order__prescription__patient",
            "order__prescription__doctor__user",
            "dispensed_by__staff_assignment__user",
        ).prefetch_related(
            "items__order_item",
            "items__stock_batch__inventory__medicine",
        ),
        pk=pk,
    )
    assignment = (
        active_pharmacy_assignments(request.user)
        .filter(pharmacy_id=dispense.order.pharmacy_id)
        .first()
    )
    pharmacy = dispense.order.pharmacy
    prescription = dispense.order.prescription
    can_record_payment = bool(
        assignment
        and dispense.status == Dispense.Status.COMPLETED
        and dispense.balance_due > Decimal("0.00")
        and request.user.has_perm("pharmacy.change_dispense")
    )

    return render(
        request,
        "pharmacy/dispense_receipt.html",
        _context(
            request,
            dispense=dispense,
            dispense_items=list(dispense.items.all().order_by("id")),
            order=dispense.order,
            prescription=prescription,
            patient=getattr(prescription, "patient", None),
            doctor=getattr(prescription, "doctor", None),
            pharmacy=pharmacy,
            hospital=pharmacy.branch.hospital,
            can_record_payment=can_record_payment,
        ),
    )


@pharmacy_portal_required
@require_http_methods(["GET", "POST"])
def record_payment(request: HttpRequest, pk: int) -> HttpResponse:
    dispense = get_object_or_404(
        _accessible_dispense_queryset(request.user).select_related(
            "order",
            "order__pharmacy",
        ),
        pk=pk,
    )
    _assignment_for_pharmacy(request.user, dispense.order.pharmacy_id)
    if dispense.status != Dispense.Status.COMPLETED:
        messages.error(request, "Payments can only be recorded for a completed dispense.")
        return redirect("pharmacy:dispense_receipt", pk=dispense.pk)
    if dispense.balance_due <= Decimal("0.00"):
        messages.info(request, "This dispense is already fully paid.")
        return redirect("pharmacy:dispense_receipt", pk=dispense.pk)

    form = RecordPaymentForm(
        request.POST if request.method == "POST" else None,
        dispense=dispense,
    )

    if request.method == "POST" and form.is_valid():
        try:
            with transaction.atomic():
                locked = Dispense.objects.select_for_update().select_related(
                    "order",
                    "order__pharmacy",
                ).get(pk=dispense.pk)
                _assignment_for_pharmacy(request.user, locked.order.pharmacy_id)
                locked_form = RecordPaymentForm(request.POST, dispense=locked)
                if not locked_form.is_valid():
                    form = locked_form
                    raise ValidationError("The payment data changed; review the form and try again.")

                data = locked_form.payment_data()
                locked.amount_paid = data["amount_paid"]
                locked.payment_status = data["payment_status"]
                locked.payment_method = data["payment_method"]
                locked.transaction_reference = data["transaction_reference"]
                if data["received_by_name"]:
                    locked.received_by_name = data["received_by_name"]
                locked.notes = _payment_note(
                    locked.notes,
                    amount=data["amount_received"],
                    user=request.user,
                    note=data["notes"],
                )
                locked.save()

            messages.success(request, "Payment was recorded successfully.")
            return redirect("pharmacy:dispense_receipt", pk=dispense.pk)
        except ValidationError as error:
            if not form.errors:
                _add_validation_to_form(form, error)

    return render(
        request,
        "pharmacy/record_payment.html",
        _context(
            request,
            form=form,
            dispense=dispense,
            page_title=f"Record payment for {dispense.receipt_number}",
            submit_label="Record payment",
            cancel_url=reverse("pharmacy:dispense_receipt", kwargs={"pk": dispense.pk}),
        ),
    )


@pharmacy_portal_required
@require_http_methods(["GET", "POST"])
def void_dispense(request: HttpRequest, pk: int) -> HttpResponse:
    dispense = get_object_or_404(
        _accessible_dispense_queryset(request.user).select_related(
            "order",
            "order__pharmacy",
        ),
        pk=pk,
    )
    assignment = _assignment_for_pharmacy(request.user, dispense.order.pharmacy_id)
    form = VoidDispenseForm(request.POST if request.method == "POST" else None)

    if request.method == "POST" and form.is_valid():
        try:
            void_completed_dispense(
                dispense=dispense,
                pharmacist_assignment=assignment,
                reason=form.cleaned_data["reason"],
            )
            messages.success(request, "The dispense was voided and stock was restored.")
            return redirect("pharmacy:dispense_detail", pk=dispense.pk)
        except ValidationError as error:
            _add_validation_to_form(form, error)

    return render(
        request,
        "pharmacy/action_form.html",
        _context(
            request,
            form=form,
            order=dispense.order,
            dispense=dispense,
            page_title=f"Void dispense {dispense.receipt_number}",
            submit_label="Void dispense",
            danger_action=True,
            cancel_url=reverse("pharmacy:dispense_detail", kwargs={"pk": dispense.pk}),
        ),
    )


# ---------------------------------------------------------------------------
# Direct sales / POS
# ---------------------------------------------------------------------------
@pharmacy_portal_required
@require_GET
def sale_list(request: HttpRequest) -> HttpResponse:
    pharmacies = accessible_pharmacies(request.user)
    queryset = (
        PharmacySale.objects.filter(pharmacy__in=pharmacies)
        .select_related(
            "pharmacy",
            "pharmacy__branch",
            "cashier__staff_assignment__user",
        )
        .order_by("-created_at", "-pk")
    )
    filters = {
        "q": (request.GET.get("q") or "").strip(),
        "status": (request.GET.get("status") or "").strip(),
        "payment_status": (request.GET.get("payment_status") or "").strip(),
        "pharmacy": (request.GET.get("pharmacy") or "").strip(),
    }

    if filters["q"]:
        q = filters["q"]
        search = (
            Q(customer_name__icontains=q)
            | Q(customer_phone__icontains=q)
            | Q(transaction_reference__icontains=q)
            | Q(items__medicine__generic_name__icontains=q)
            | Q(items__medicine__brand_name__icontains=q)
        )
        if q.isdigit():
            search |= Q(pk=int(q))
        queryset = queryset.filter(search).distinct()

    valid_statuses = {value for value, _label in PharmacySale.Status.choices}
    if filters["status"] in valid_statuses:
        queryset = queryset.filter(status=filters["status"])

    valid_payment = {value for value, _label in PharmacySale.PaymentStatus.choices}
    if filters["payment_status"] in valid_payment:
        queryset = queryset.filter(payment_status=filters["payment_status"])

    selected = _selected_accessible_pharmacy(request, filters["pharmacy"])
    if selected:
        queryset = queryset.filter(pharmacy=selected)
    elif filters["pharmacy"]:
        filters["pharmacy"] = ""

    return render(
        request,
        "pharmacy/sale_list.html",
        _context(
            request,
            page_obj=_paginate(request, queryset),
            pharmacies=pharmacies,
            status_choices=PharmacySale.Status.choices,
            payment_status_choices=PharmacySale.PaymentStatus.choices,
            filters=filters,
        ),
    )


@pharmacy_portal_required
@require_http_methods(["GET", "POST"])
def sale_create(request: HttpRequest) -> HttpResponse:
    initial_pharmacy = _selected_accessible_pharmacy(request, request.GET.get("pharmacy"))
    form = DirectSaleForm(
        request.POST if request.method == "POST" else None,
        user=request.user,
        pharmacy=initial_pharmacy,
    )

    if request.method == "POST":
        form_valid = form.is_valid()
        selected_pharmacy = form.cleaned_data.get("pharmacy") if form_valid else form.selected_pharmacy
        formset = DirectSaleItemFormSet(
            request.POST,
            prefix="items",
            pharmacy=selected_pharmacy,
        )
        formset_valid = formset.is_valid()

        if form_valid and formset_valid:
            try:
                assignment = _assignment_for_pharmacy(request.user, selected_pharmacy)
                sale = create_direct_sale(
                    cashier_assignment=assignment,
                    items=formset.items_data(),
                    **form.service_data(),
                )
                messages.success(request, f"Sale {sale.sale_number} was completed.")
                return redirect("pharmacy:sale_receipt", pk=sale.pk)
            except ValidationError as error:
                if hasattr(error, "message_dict") and "items" in error.message_dict:
                    _add_validation_to_formset(formset, error)
                else:
                    _add_validation_to_form(form, error)
    else:
        selected_pharmacy = form.selected_pharmacy
        formset = DirectSaleItemFormSet(prefix="items", pharmacy=selected_pharmacy)

    return render(
        request,
        "pharmacy/sale_form.html",
        _context(
            request,
            form=form,
            formset=formset,
            page_title="New direct sale",
            submit_label="Complete sale",
            cancel_url=reverse("pharmacy:sales"),
        ),
    )


@pharmacy_portal_required
@require_GET
def sale_detail(request: HttpRequest, pk: int) -> HttpResponse:
    sale = get_object_or_404(
        _accessible_sale_queryset(request.user).select_related(
            "pharmacy",
            "pharmacy__branch",
            "pharmacy__branch__hospital",
            "cashier__staff_assignment__user",
            "voided_by",
        ).prefetch_related(
            "items__medicine",
            "items__allocations__stock_batch",
        ),
        pk=pk,
    )
    assignment = (
        active_pharmacy_assignments(request.user)
        .filter(pharmacy_id=sale.pharmacy_id)
        .order_by("-is_manager", "id")
        .first()
    )
    can_record_payment = bool(
        assignment
        and sale.status == PharmacySale.Status.COMPLETED
        and sale.balance_due > Decimal("0.00")
        and request.user.has_perm("pharmacy.change_pharmacysale")
    )
    can_void = bool(
        assignment
        and sale.status == PharmacySale.Status.COMPLETED
        and request.user.has_perm("pharmacy.delete_pharmacysale")
    )

    return render(
        request,
        "pharmacy/sale_detail.html",
        _context(
            request,
            sale=sale,
            sale_items=list(sale.items.all().order_by("id")),
            can_record_payment=can_record_payment,
            can_void=can_void,
        ),
    )


@pharmacy_portal_required
@require_GET
def sale_receipt(request: HttpRequest, pk: int) -> HttpResponse:
    sale = get_object_or_404(
        _accessible_sale_queryset(request.user).select_related(
            "pharmacy",
            "pharmacy__branch",
            "pharmacy__branch__hospital",
            "cashier__staff_assignment__user",
        ).prefetch_related(
            "items__medicine",
            "items__allocations__stock_batch",
        ),
        pk=pk,
    )
    assignment = active_pharmacy_assignments(request.user).filter(
        pharmacy_id=sale.pharmacy_id,
    ).first()
    can_record_payment = bool(
        assignment
        and sale.status == PharmacySale.Status.COMPLETED
        and sale.balance_due > Decimal("0.00")
        and request.user.has_perm("pharmacy.change_pharmacysale")
    )
    return render(
        request,
        "pharmacy/sale_receipt.html",
        _context(
            request,
            sale=sale,
            sale_items=list(sale.items.all().order_by("id")),
            pharmacy=sale.pharmacy,
            hospital=sale.pharmacy.branch.hospital,
            can_record_payment=can_record_payment,
        ),
    )


@pharmacy_portal_required
@require_http_methods(["GET", "POST"])
def sale_payment(request: HttpRequest, pk: int) -> HttpResponse:
    sale = get_object_or_404(
        _accessible_sale_queryset(request.user).select_related("pharmacy"),
        pk=pk,
    )
    assignment = _assignment_for_pharmacy(request.user, sale.pharmacy_id)
    if sale.status != PharmacySale.Status.COMPLETED:
        messages.error(request, "Payments can only be recorded for a completed sale.")
        return redirect("pharmacy:sale_detail", pk=sale.pk)
    if sale.balance_due <= Decimal("0.00"):
        messages.info(request, "This sale is already fully paid.")
        return redirect("pharmacy:sale_detail", pk=sale.pk)

    form = DirectSalePaymentForm(
        request.POST if request.method == "POST" else None,
        sale=sale,
    )

    if request.method == "POST" and form.is_valid():
        try:
            record_direct_sale_payment(
                sale=sale,
                cashier_assignment=assignment,
                **form.service_data(),
            )
            messages.success(request, "Sale payment was recorded.")
            return redirect("pharmacy:sale_receipt", pk=sale.pk)
        except ValidationError as error:
            _add_validation_to_form(form, error)

    return render(
        request,
        "pharmacy/sale_payment.html",
        _context(
            request,
            form=form,
            sale=sale,
            page_title=f"Record payment for {sale.sale_number}",
            submit_label="Record payment",
            cancel_url=reverse("pharmacy:sale_detail", kwargs={"pk": sale.pk}),
        ),
    )


@pharmacy_portal_required
@require_http_methods(["GET", "POST"])
def sale_void(request: HttpRequest, pk: int) -> HttpResponse:
    sale = get_object_or_404(
        _accessible_sale_queryset(request.user).select_related("pharmacy"),
        pk=pk,
    )
    assignment = _assignment_for_pharmacy(request.user, sale.pharmacy_id)
    form = VoidDirectSaleForm(request.POST if request.method == "POST" else None)

    if request.method == "POST" and form.is_valid():
        try:
            void_direct_sale(
                sale=sale,
                pharmacist_assignment=assignment,
                reason=form.cleaned_data["reason"],
                voided_by=request.user,
            )
            messages.success(request, "The sale was voided and stock was restored.")
            return redirect("pharmacy:sale_detail", pk=sale.pk)
        except ValidationError as error:
            _add_validation_to_form(form, error)

    return render(
        request,
        "pharmacy/action_form.html",
        _context(
            request,
            form=form,
            page_title=f"Void sale {sale.sale_number}",
            submit_label="Void sale",
            danger_action=True,
            cancel_url=reverse("pharmacy:sale_detail", kwargs={"pk": sale.pk}),
            sale=sale,
        ),
    )


# ---------------------------------------------------------------------------
# Inventory and medicine catalogue
# ---------------------------------------------------------------------------
@pharmacy_portal_required
@require_GET
def inventory_list(request: HttpRequest) -> HttpResponse:
    pharmacies = accessible_pharmacies(request.user)
    queryset = _available_inventory_queryset(request.user).order_by(
        "pharmacy__name",
        "medicine__generic_name",
        "medicine__brand_name",
    )
    filters = {
        "q": (request.GET.get("q") or "").strip(),
        "pharmacy": (request.GET.get("pharmacy") or "").strip(),
        "stock": (request.GET.get("stock") or "").strip(),
    }

    if filters["q"]:
        q = filters["q"]
        queryset = queryset.filter(
            Q(medicine__generic_name__icontains=q)
            | Q(medicine__brand_name__icontains=q)
            | Q(medicine__code__icontains=q)
            | Q(medicine__barcode__icontains=q)
        )

    selected = _selected_accessible_pharmacy(request, filters["pharmacy"])
    if selected:
        queryset = queryset.filter(pharmacy=selected)
    elif filters["pharmacy"]:
        filters["pharmacy"] = ""

    if filters["stock"] == "out":
        queryset = queryset.filter(available_quantity=0)
    elif filters["stock"] == "low":
        queryset = queryset.filter(available_quantity__lte=F("reorder_level"))
    elif filters["stock"] == "available":
        queryset = queryset.filter(available_quantity__gt=0)
    else:
        filters["stock"] = ""

    return render(
        request,
        "pharmacy/inventory_list.html",
        _context(
            request,
            page_obj=_paginate(request, queryset),
            pharmacies=pharmacies,
            filters=filters,
        ),
    )


@pharmacy_portal_required
@require_GET
def medicine_list(request: HttpRequest) -> HttpResponse:
    pharmacies = accessible_pharmacies(request.user)
    hospital_ids = pharmacies.values_list("branch__hospital_id", flat=True).distinct()
    manageable = _manageable_pharmacies(request.user)
    manageable_hospital_ids = list(
        manageable.values_list("branch__hospital_id", flat=True).distinct()
    )
    query = (request.GET.get("q") or "").strip()

    medicines = Medicine.objects.filter(hospital_id__in=hospital_ids).select_related("hospital")
    if query:
        medicines = medicines.filter(
            Q(generic_name__icontains=query)
            | Q(brand_name__icontains=query)
            | Q(code__icontains=query)
            | Q(barcode__icontains=query)
            | Q(manufacturer__icontains=query)
        )

    medicines = medicines.order_by("generic_name", "brand_name", "strength")
    return render(
        request,
        "pharmacy/medicine_list.html",
        _context(
            request,
            page_obj=_paginate(request, medicines),
            query=query,
            can_manage_medicines=bool(manageable_hospital_ids),
            manageable_hospital_ids=manageable_hospital_ids,
        ),
    )


@pharmacy_portal_required
@require_http_methods(["GET", "POST"])
def medicine_create(request: HttpRequest) -> HttpResponse:
    pharmacies = _manageable_pharmacies(request.user)
    if not pharmacies.exists():
        raise PermissionDenied("An active pharmacy manager assignment is required to create medicines.")

    form = MedicineManagementForm(
        request.POST if request.method == "POST" else None,
        pharmacies=pharmacies,
    )
    if request.method == "POST" and form.is_valid():
        try:
            medicine = form.save()
            messages.success(request, f"Medicine {medicine.display_name} was created.")
            return redirect("pharmacy:medicines")
        except ValidationError as error:
            _add_validation_to_form(form, error)
        except IntegrityError:
            form.add_error(None, "A medicine with the same code or barcode already exists.")

    return render(
        request,
        "pharmacy/medicine_form.html",
        _context(
            request,
            form=form,
            page_title="Add medicine",
            page_subtitle="Create medicine master data and optionally add it to inventory.",
            submit_label="Create medicine",
            cancel_url=reverse("pharmacy:medicines"),
            is_edit=False,
        ),
    )


@pharmacy_portal_required
@require_http_methods(["GET", "POST"])
def medicine_edit(request: HttpRequest, pk: int) -> HttpResponse:
    manageable = _manageable_pharmacies(request.user)
    manageable_hospital_ids = manageable.values_list("branch__hospital_id", flat=True)
    medicine = get_object_or_404(
        Medicine.objects.select_related("hospital").filter(
            hospital_id__in=manageable_hospital_ids,
        ),
        pk=pk,
    )
    pharmacies = manageable.filter(branch__hospital_id=medicine.hospital_id)
    form = MedicineManagementForm(
        request.POST if request.method == "POST" else None,
        instance=medicine,
        pharmacies=pharmacies,
    )

    if request.method == "POST" and form.is_valid():
        try:
            medicine = form.save()
            messages.success(request, f"Medicine {medicine.display_name} was updated.")
            return redirect("pharmacy:medicines")
        except ValidationError as error:
            _add_validation_to_form(form, error)
        except IntegrityError:
            form.add_error(None, "A medicine with the same code or barcode already exists.")

    return render(
        request,
        "pharmacy/medicine_form.html",
        _context(
            request,
            form=form,
            medicine=medicine,
            page_title="Edit medicine",
            page_subtitle=medicine.display_name,
            submit_label="Save changes",
            cancel_url=reverse("pharmacy:medicines"),
            is_edit=True,
        ),
    )


@pharmacy_portal_required
@require_POST
def medicine_toggle_active(request: HttpRequest, pk: int) -> HttpResponse:
    manageable = _manageable_pharmacies(request.user)
    manageable_hospital_ids = manageable.values_list("branch__hospital_id", flat=True)
    medicine = get_object_or_404(
        Medicine.objects.filter(hospital_id__in=manageable_hospital_ids),
        pk=pk,
    )

    with transaction.atomic():
        medicine = Medicine.objects.select_for_update().get(pk=medicine.pk)
        medicine.is_active = not medicine.is_active
        medicine.save(update_fields=["is_active", "updated_at"])
        PharmacyInventory.objects.filter(medicine=medicine).update(
            is_active=medicine.is_active,
            updated_at=timezone.now(),
        )

    state = "activated" if medicine.is_active else "deactivated"
    messages.success(request, f"Medicine {medicine.display_name} was {state}.")
    return redirect("pharmacy:medicines")


@pharmacy_portal_required
@require_GET
def batch_list(request: HttpRequest) -> HttpResponse:
    today = timezone.localdate()
    queryset = (
        StockBatch.objects.filter(
            inventory__pharmacy__in=accessible_pharmacies(request.user),
        )
        .select_related(
            "inventory",
            "inventory__pharmacy",
            "inventory__medicine",
        )
        .order_by("expiry_date", "inventory__medicine__generic_name", "pk")
    )
    filters = {
        "q": (request.GET.get("q") or "").strip(),
        "state": (request.GET.get("state") or "").strip(),
    }

    if filters["q"]:
        q = filters["q"]
        queryset = queryset.filter(
            Q(batch_number__icontains=q)
            | Q(supplier_name__icontains=q)
            | Q(inventory__medicine__generic_name__icontains=q)
            | Q(inventory__medicine__brand_name__icontains=q)
            | Q(inventory__medicine__code__icontains=q)
        )

    if filters["state"] == "available":
        queryset = queryset.filter(
            is_active=True,
            quantity_on_hand__gt=0,
            expiry_date__gte=today,
        )
    elif filters["state"] == "empty":
        queryset = queryset.filter(quantity_on_hand=0)
    elif filters["state"] == "expired":
        queryset = queryset.filter(expiry_date__lt=today)
    else:
        filters["state"] = ""

    return render(
        request,
        "pharmacy/batch_list.html",
        _context(
            request,
            page_obj=_paginate(request, queryset),
            filters=filters,
        ),
    )


@pharmacy_portal_required
@require_http_methods(["GET", "POST"])
def receive_stock(request: HttpRequest) -> HttpResponse:
    form = StockReceiptForm(
        request.POST if request.method == "POST" else None,
        user=request.user,
    )
    if request.method == "POST" and form.is_valid():
        try:
            batch = form.save(user=request.user)
            messages.success(
                request,
                f"Batch {batch.batch_number} was received with {batch.received_quantity} units.",
            )
            return redirect("pharmacy:batches")
        except ValidationError as error:
            _add_validation_to_form(form, error)
        except IntegrityError:
            form.add_error("batch_number", "This batch number already exists for the inventory item.")

    return render(
        request,
        "pharmacy/action_form.html",
        _context(
            request,
            form=form,
            page_title="Receive stock",
            submit_label="Receive stock",
            cancel_url=reverse("pharmacy:batches"),
        ),
    )


@pharmacy_portal_required
@require_GET
def stock_movement_list(request: HttpRequest) -> HttpResponse:
    queryset = (
        StockMovement.objects.filter(
            stock_batch__inventory__pharmacy__in=accessible_pharmacies(request.user),
        )
        .select_related(
            "stock_batch",
            "stock_batch__inventory",
            "stock_batch__inventory__pharmacy",
            "stock_batch__inventory__medicine",
            "created_by",
        )
        .order_by("-created_at", "-pk")
    )
    filters = {
        "q": (request.GET.get("q") or "").strip(),
        "type": (request.GET.get("type") or "").strip(),
    }

    if filters["q"]:
        q = filters["q"]
        queryset = queryset.filter(
            Q(stock_batch__batch_number__icontains=q)
            | Q(stock_batch__inventory__medicine__generic_name__icontains=q)
            | Q(stock_batch__inventory__medicine__brand_name__icontains=q)
            | Q(notes__icontains=q)
            | Q(created_by__email__icontains=q)
        )

    valid_types = {value for value, _label in StockMovement.Types.choices}
    if filters["type"] in valid_types:
        queryset = queryset.filter(movement_type=filters["type"])
    else:
        filters["type"] = ""

    return render(
        request,
        "pharmacy/movement_list.html",
        _context(
            request,
            page_obj=_paginate(request, queryset),
            movement_choices=StockMovement.Types.choices,
            filters=filters,
        ),
    )


# ---------------------------------------------------------------------------
# Doctor sends a prescription to an integrated pharmacy
# ---------------------------------------------------------------------------
@login_required
@require_http_methods(["GET", "POST"])
def send_prescription(request: HttpRequest, prescription_id: int) -> HttpResponse:
    prescription = get_object_or_404(
        Prescription.objects.select_related(
            "doctor",
            "doctor__user",
            "patient",
            "appointment",
            "appointment__branch",
            "appointment__branch__hospital",
        ).prefetch_related("medications"),
        pk=prescription_id,
    )

    if not user_can_manage_prescription(request.user, prescription):
        raise PermissionDenied("Only the prescribing doctor or an administrator can send this prescription.")

    form = SendPrescriptionToPharmacyForm(
        request.POST if request.method == "POST" else None,
        prescription=prescription,
    )

    if request.method == "POST" and form.is_valid():
        try:
            order = send_prescription_to_pharmacy(
                prescription=prescription,
                pharmacy=form.cleaned_data["pharmacy"],
                sent_by=request.user,
                priority=form.cleaned_data["priority"],
                doctor_notes=form.cleaned_data.get("doctor_notes", ""),
            )
            messages.success(request, "The prescription was sent to the pharmacy.")
            return redirect("pharmacy:order_detail", pk=order.pk)
        except ValidationError as error:
            _add_validation_to_form(form, error)

    return render(
        request,
        "pharmacy/send_prescription.html",
        _context(
            request,
            form=form,
            prescription=prescription,
            page_title=f"Send prescription #{prescription.pk} to pharmacy",
            submit_label="Send to pharmacy",
            cancel_url=prescription.get_absolute_url(),
        ),
    )
