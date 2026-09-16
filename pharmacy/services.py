from __future__ import annotations

from collections import defaultdict
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any, Iterable, Mapping

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from appointments.models import Notification
from hospital.models import Branch, Hospital, StaffAssignment
from prescription.models import Prescription

from pharmacy.models import (
    Dispense,
    DispenseItem,
    Medicine,
    Pharmacy,
    PharmacyInventory,
    PharmacyOrder,
    PharmacyOrderItem,
    PharmacySale,
    PharmacySaleAllocation,
    PharmacySaleItem,
    PharmacyStaffAssignment,
    StockBatch,
    StockMovement,
)


MONEY_PLACES = Decimal("0.01")


ACTIVE_ORDER_STATUSES = (
    PharmacyOrder.Status.SENT,
    PharmacyOrder.Status.ACCEPTED,
    PharmacyOrder.Status.IN_PROGRESS,
    PharmacyOrder.Status.PARTIALLY_DISPENSED,
)

PROCESSABLE_ORDER_STATUSES = (
    PharmacyOrder.Status.ACCEPTED,
    PharmacyOrder.Status.IN_PROGRESS,
    PharmacyOrder.Status.PARTIALLY_DISPENSED,
)


def _object_pk(value: Any, field_name: str) -> int:
    pk = getattr(value, "pk", value)

    if pk is None:
        raise ValidationError(
            {field_name: f"A valid {field_name} is required."}
        )

    try:
        return int(pk)
    except (TypeError, ValueError) as exc:
        raise ValidationError(
            {field_name: f"Invalid {field_name}."}
        ) from exc


def _money(
    value: Any,
    field_name: str,
    *,
    allow_zero: bool = True,
) -> Decimal:
    try:
        amount = Decimal(str(value)).quantize(
            MONEY_PLACES,
            rounding=ROUND_HALF_UP,
        )
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValidationError(
            {field_name: f"Invalid {field_name.replace('_', ' ')}."}
        ) from exc

    if amount < Decimal("0.00"):
        raise ValidationError(
            {field_name: "The amount cannot be negative."}
        )

    if not allow_zero and amount == Decimal("0.00"):
        raise ValidationError(
            {field_name: "The amount must be greater than zero."}
        )

    return amount


def _locked_prescription(value: Prescription | int) -> Prescription:
    prescription_id = _object_pk(value, "prescription")

    try:
        return (
            Prescription.objects.select_for_update(of=("self",))
            .select_related(
                "doctor__user",
                "appointment",
                "appointment__branch",
                "appointment__branch__hospital",
            )
            .get(pk=prescription_id)
        )
    except Prescription.DoesNotExist:
        raise ValidationError(
            {"prescription": "Prescription does not exist."}
        ) from None


def _locked_pharmacy(value: Pharmacy | int) -> Pharmacy:
    pharmacy_id = _object_pk(value, "pharmacy")

    try:
        return (
            Pharmacy.objects.select_for_update(of=("self",))
            .select_related("branch", "branch__hospital")
            .get(pk=pharmacy_id)
        )
    except Pharmacy.DoesNotExist:
        raise ValidationError(
            {"pharmacy": "Pharmacy does not exist or is deleted."}
        ) from None


def _locked_order(value: PharmacyOrder | int) -> PharmacyOrder:
    order_id = _object_pk(value, "order")

    try:
        return (
            PharmacyOrder.objects.select_for_update(of=("self",))
            .select_related(
                "prescription",
                "prescription__doctor__user",
                "pharmacy",
                "pharmacy__branch",
                "pharmacy__branch__hospital",
                "sent_by",
                "assigned_to",
            )
            .get(pk=order_id)
        )
    except PharmacyOrder.DoesNotExist:
        raise ValidationError(
            {"order": "Pharmacy order does not exist or is deleted."}
        ) from None


def _locked_sale(value: PharmacySale | int) -> PharmacySale:
    sale_id = _object_pk(value, "sale")

    try:
        return (
            PharmacySale.objects.select_for_update(of=("self",))
            .select_related(
                "pharmacy",
                "pharmacy__branch",
                "pharmacy__branch__hospital",
                "cashier",
                "cashier__staff_assignment",
                "cashier__staff_assignment__user",
            )
            .get(pk=sale_id)
        )
    except PharmacySale.DoesNotExist:
        raise ValidationError(
            {"sale": "Direct pharmacy sale does not exist or is deleted."}
        ) from None


def _locked_assignment(
    value: PharmacyStaffAssignment | int,
) -> PharmacyStaffAssignment:
    assignment_id = _object_pk(value, "pharmacist_assignment")

    try:
        return (
            PharmacyStaffAssignment.objects.select_for_update(of=("self",))
            .select_related(
                "pharmacy",
                "pharmacy__branch",
                "pharmacy__branch__hospital",
                "staff_assignment",
                "staff_assignment__user",
            )
            .get(pk=assignment_id)
        )
    except PharmacyStaffAssignment.DoesNotExist:
        raise ValidationError(
            {
                "pharmacist_assignment": (
                    "Pharmacist assignment does not exist or is deleted."
                )
            }
        ) from None


def _validate_pharmacy(pharmacy: Pharmacy) -> None:
    if not pharmacy.is_active or pharmacy.is_deleted:
        raise ValidationError(
            {"pharmacy": "The selected pharmacy is inactive."}
        )

    if not pharmacy.branch.is_active or pharmacy.branch.is_deleted:
        raise ValidationError(
            {"pharmacy": "The selected pharmacy branch is inactive."}
        )

    hospital = pharmacy.branch.hospital

    if not hospital.is_active or hospital.is_deleted:
        raise ValidationError(
            {"pharmacy": "The selected hospital is inactive."}
        )


def _validate_pharmacist_assignment(
    assignment: PharmacyStaffAssignment,
    pharmacy_id: int,
) -> None:
    errors = {}

    if assignment.pharmacy_id != pharmacy_id:
        errors["pharmacist_assignment"] = (
            "The pharmacist does not belong to this pharmacy."
        )

    if not assignment.is_active or assignment.is_deleted:
        errors["pharmacist_assignment"] = (
            "The pharmacist assignment is inactive."
        )

    hospital_assignment = assignment.staff_assignment

    if (
        not hospital_assignment.is_active
        or hospital_assignment.is_deleted
    ):
        errors["pharmacist_assignment"] = (
            "The hospital staff assignment is inactive."
        )

    if hospital_assignment.role != "pharmacist":
        errors["pharmacist_assignment"] = (
            "The staff assignment must have the pharmacist role."
        )

    if getattr(hospital_assignment.user, "role", None) != "pharmacist":
        errors["pharmacist_assignment"] = (
            "The linked user must have the pharmacist account role."
        )

    if errors:
        raise ValidationError(errors)


def _validate_order_assignment(
    order: PharmacyOrder,
    assignment: PharmacyStaffAssignment,
) -> None:
    _validate_pharmacist_assignment(
        assignment,
        order.pharmacy_id,
    )

    if (
        order.assigned_to_id
        and order.assigned_to_id != assignment.pk
        and not assignment.is_manager
    ):
        raise ValidationError(
            {
                "pharmacist_assignment": (
                    "This order is assigned to another pharmacist."
                )
            }
        )


@transaction.atomic
def create_standalone_pharmacy(
    *,
    name: str,
    code: str,
    owner_user: Any,
    phone: str = "",
    email: str = "",
    address: str = "",
    license_number: str = "",
) -> tuple[Pharmacy, PharmacyStaffAssignment]:
    """
    Create a standalone pharmacy with its private administrative location.

    The current ClinicHub inventory models use Hospital and Branch as their
    organization boundary. A standalone pharmacy therefore receives a private
    system-managed Hospital/Branch pair. The UI can hide those technical
    records while the database keeps tenant isolation and existing relations.
    """
    clean_name = " ".join((name or "").split()).strip()
    clean_code = (code or "").strip().upper()

    errors = {}

    if not clean_name:
        errors["name"] = "Pharmacy name is required."

    if not clean_code:
        errors["code"] = "Pharmacy code is required."

    if len(clean_code) > 24:
        errors["code"] = (
            "Standalone pharmacy code cannot exceed 24 characters."
        )

    if (
        not owner_user
        or not getattr(owner_user, "is_authenticated", False)
    ):
        errors["owner_user"] = (
            "An authenticated pharmacy owner is required."
        )
    elif getattr(owner_user, "role", None) != "pharmacist":
        errors["owner_user"] = (
            "The standalone pharmacy owner must have the pharmacist role."
        )

    organization_code = f"ST-{clean_code}"

    if Hospital.all_objects.filter(code=organization_code).exists():
        errors["code"] = (
            "A standalone pharmacy with this code already exists."
        )

    if errors:
        raise ValidationError(errors)

    hospital = Hospital.objects.create(
        name=f"{clean_name} Organization",
        code=organization_code,
        phone=(phone or "").strip(),
        email=(email or "").strip(),
        address=(address or "").strip(),
        is_active=True,
    )

    branch = Branch.objects.create(
        hospital=hospital,
        name="Main Branch",
        code="MAIN",
        phone=(phone or "").strip(),
        email=(email or "").strip(),
        address=(address or "").strip(),
        is_active=True,
    )

    pharmacy = Pharmacy.objects.create(
        branch=branch,
        name=clean_name,
        code=clean_code,
        operating_mode=Pharmacy.OperatingModes.STANDALONE,
        pharmacy_type=Pharmacy.Types.OUTPATIENT,
        phone=(phone or "").strip(),
        email=(email or "").strip(),
        location=(address or "").strip(),
        license_number=(license_number or "").strip(),
        is_active=True,
    )

    has_primary_assignment = StaffAssignment.objects.filter(
        user=owner_user,
        is_primary=True,
        is_active=True,
    ).exists()

    hospital_assignment = StaffAssignment.objects.create(
        user=owner_user,
        hospital=hospital,
        branch=branch,
        department=None,
        role=StaffAssignment.Roles.PHARMACIST,
        is_primary=not has_primary_assignment,
        is_active=True,
        start_date=timezone.localdate(),
    )

    pharmacy_assignment = PharmacyStaffAssignment.objects.create(
        pharmacy=pharmacy,
        staff_assignment=hospital_assignment,
        is_manager=True,
        is_active=True,
        start_date=timezone.localdate(),
    )

    return pharmacy, pharmacy_assignment


def _authorize_prescription_sender(
    prescription: Prescription,
    user: Any,
) -> None:
    if not user or not getattr(user, "is_authenticated", False):
        raise ValidationError(
            {"sent_by": "An authenticated user is required."}
        )

    if getattr(user, "is_superuser", False):
        return

    if getattr(user, "role", None) == "admin":
        return

    doctor_user_id = getattr(
        getattr(prescription, "doctor", None),
        "user_id",
        None,
    )

    if user.pk != doctor_user_id:
        raise ValidationError(
            {
                "sent_by": (
                    "Only the prescribing doctor or an administrator "
                    "can send this prescription."
                )
            }
        )


def _validate_prescription_hospital(
    prescription: Prescription,
    pharmacy: Pharmacy,
) -> None:
    if pharmacy.operating_mode != Pharmacy.OperatingModes.INTEGRATED:
        raise ValidationError(
            {
                "pharmacy": (
                    "Hospital prescriptions can only be sent to an "
                    "integrated pharmacy. Use the direct-sale workflow "
                    "for a standalone pharmacy."
                )
            }
        )

    appointment = prescription.appointment
    appointment_branch_id = getattr(appointment, "branch_id", None)

    if not appointment_branch_id:
        return

    if appointment.branch.hospital_id != pharmacy.branch.hospital_id:
        raise ValidationError(
            {
                "pharmacy": (
                    "The prescription and pharmacy must belong "
                    "to the same hospital."
                )
            }
        )


def _find_exact_medicine(
    medication_name: str,
    hospital_id: int,
) -> Medicine | None:
    normalized_name = " ".join(
        (medication_name or "").split()
    ).strip()

    if not normalized_name:
        return None

    matches = list(
        Medicine.objects.filter(
            hospital_id=hospital_id,
            is_active=True,
        )
        .filter(
            Q(generic_name__iexact=normalized_name)
            | Q(brand_name__iexact=normalized_name)
        )
        .order_by("id")[:2]
    )

    return matches[0] if len(matches) == 1 else None


@transaction.atomic
def send_prescription_to_pharmacy(
    *,
    prescription: Prescription | int,
    pharmacy: Pharmacy | int,
    sent_by: Any,
    priority: str = PharmacyOrder.Priority.NORMAL,
    doctor_notes: str = "",
) -> PharmacyOrder:
    locked_prescription = _locked_prescription(prescription)
    locked_pharmacy = _locked_pharmacy(pharmacy)

    _validate_pharmacy(locked_pharmacy)
    _authorize_prescription_sender(locked_prescription, sent_by)
    _validate_prescription_hospital(
        locked_prescription,
        locked_pharmacy,
    )

    # A completed prescription is finalized and remains eligible for dispensing.
    # Only canceled prescriptions must be blocked.
    if locked_prescription.status == "canceled":
        raise ValidationError(
            {
                "prescription": (
                    "A canceled prescription cannot be sent."
                )
            }
        )

    valid_priorities = {
        value for value, _label in PharmacyOrder.Priority.choices
    }

    if priority not in valid_priorities:
        raise ValidationError(
            {"priority": "Invalid pharmacy order priority."}
        )

    medications = list(
        locked_prescription.medications.all().order_by("id")
    )

    if not medications:
        raise ValidationError(
            {
                "prescription": (
                    "The prescription must contain at least one medication."
                )
            }
        )

    existing_order = (
        PharmacyOrder.objects.select_for_update(of=("self",))
        .filter(
            prescription=locked_prescription,
            status__in=ACTIVE_ORDER_STATUSES,
        )
        .first()
    )

    if existing_order:
        raise ValidationError(
            {
                "prescription": (
                    "This prescription already has an active pharmacy order."
                )
            }
        )

    order = PharmacyOrder.objects.create(
        prescription=locked_prescription,
        pharmacy=locked_pharmacy,
        sent_by=sent_by,
        priority=priority,
        status=PharmacyOrder.Status.SENT,
        doctor_notes=(doctor_notes or "").strip(),
    )

    hospital_id = locked_pharmacy.branch.hospital_id

    for medication in medications:
        matched_medicine = _find_exact_medicine(
            medication.name,
            hospital_id,
        )

        requested_unit = (
            matched_medicine.dispensing_unit
            if matched_medicine
            else "unit"
        )

        PharmacyOrderItem.objects.create(
            order=order,
            prescription_medication=medication,
            medicine=matched_medicine,
            medication_name=medication.name,
            dosage=medication.dosage,
            requested_quantity=1,
            requested_unit=requested_unit,
            status=PharmacyOrderItem.Status.PENDING,
        )

    return order


@transaction.atomic
def accept_pharmacy_order(
    *,
    order: PharmacyOrder | int,
    pharmacist_assignment: PharmacyStaffAssignment | int,
) -> PharmacyOrder:
    locked_order = _locked_order(order)
    locked_assignment = _locked_assignment(pharmacist_assignment)

    _validate_order_assignment(locked_order, locked_assignment)

    if (
        locked_order.status == PharmacyOrder.Status.ACCEPTED
        and locked_order.assigned_to_id == locked_assignment.pk
    ):
        return locked_order

    if locked_order.status != PharmacyOrder.Status.SENT:
        raise ValidationError(
            {"order": "Only a newly sent pharmacy order can be accepted."}
        )

    locked_order.assigned_to = locked_assignment
    locked_order.status = PharmacyOrder.Status.ACCEPTED
    locked_order.rejection_reason = ""
    locked_order.save()

    return locked_order


@transaction.atomic
def start_pharmacy_order(
    *,
    order: PharmacyOrder | int,
    pharmacist_assignment: PharmacyStaffAssignment | int,
) -> PharmacyOrder:
    locked_order = _locked_order(order)
    locked_assignment = _locked_assignment(pharmacist_assignment)

    _validate_order_assignment(locked_order, locked_assignment)

    if locked_order.status == PharmacyOrder.Status.IN_PROGRESS:
        return locked_order

    if locked_order.status != PharmacyOrder.Status.ACCEPTED:
        raise ValidationError(
            {
                "order": (
                    "The pharmacy order must be accepted before processing."
                )
            }
        )

    if not locked_order.assigned_to_id:
        locked_order.assigned_to = locked_assignment

    locked_order.status = PharmacyOrder.Status.IN_PROGRESS
    locked_order.save()

    return locked_order


@transaction.atomic
def reject_pharmacy_order(
    *,
    order: PharmacyOrder | int,
    pharmacist_assignment: PharmacyStaffAssignment | int,
    reason: str,
) -> PharmacyOrder:
    locked_order = _locked_order(order)
    locked_assignment = _locked_assignment(pharmacist_assignment)

    _validate_order_assignment(locked_order, locked_assignment)

    rejection_reason = (reason or "").strip()

    if not rejection_reason:
        raise ValidationError(
            {"reason": "A rejection reason is required."}
        )

    allowed_statuses = {
        PharmacyOrder.Status.SENT,
        PharmacyOrder.Status.ACCEPTED,
        PharmacyOrder.Status.IN_PROGRESS,
    }

    if locked_order.status not in allowed_statuses:
        raise ValidationError(
            {
                "order": (
                    "This pharmacy order cannot be rejected "
                    "in its current status."
                )
            }
        )

    if Dispense.objects.filter(
        order=locked_order,
        status=Dispense.Status.COMPLETED,
    ).exists():
        raise ValidationError(
            {
                "order": (
                    "An order with completed dispensing records "
                    "cannot be rejected."
                )
            }
        )

    locked_order.assigned_to = locked_assignment
    locked_order.status = PharmacyOrder.Status.REJECTED
    locked_order.rejection_reason = rejection_reason
    locked_order.save()

    return locked_order


@transaction.atomic
def cancel_pharmacy_order(
    *,
    order: PharmacyOrder | int,
    cancelled_by: Any,
) -> PharmacyOrder:
    locked_order = _locked_order(order)

    _authorize_prescription_sender(
        locked_order.prescription,
        cancelled_by,
    )

    if locked_order.status in {
        PharmacyOrder.Status.DISPENSED,
        PharmacyOrder.Status.REJECTED,
        PharmacyOrder.Status.CANCELLED,
    }:
        raise ValidationError(
            {
                "order": (
                    "This pharmacy order cannot be cancelled "
                    "in its current status."
                )
            }
        )

    if Dispense.objects.filter(
        order=locked_order,
        status=Dispense.Status.COMPLETED,
    ).exists():
        raise ValidationError(
            {
                "order": (
                    "An order with completed dispensing records "
                    "cannot be cancelled."
                )
            }
        )

    locked_order.status = PharmacyOrder.Status.CANCELLED
    locked_order.pharmacy_notes = (
        f"{locked_order.pharmacy_notes}\n"
        f"Cancelled by {cancelled_by}."
    ).strip()
    locked_order.save()

    return locked_order


@transaction.atomic
def assign_medicine_to_order_item(
    *,
    order_item: PharmacyOrderItem | int,
    medicine: Medicine | int,
    pharmacist_assignment: PharmacyStaffAssignment | int,
    is_substitution: bool = False,
    notes: str = "",
) -> PharmacyOrderItem:
    item_id = _object_pk(order_item, "order_item")
    medicine_id = _object_pk(medicine, "medicine")

    try:
        locked_item = (
            PharmacyOrderItem.objects.select_for_update(of=("self",))
            .select_related(
                "order",
                "order__pharmacy",
                "order__pharmacy__branch",
            )
            .get(pk=item_id)
        )
    except PharmacyOrderItem.DoesNotExist:
        raise ValidationError(
            {"order_item": "Pharmacy order item does not exist."}
        ) from None

    try:
        locked_medicine = (
            Medicine.objects.select_for_update(of=("self",))
            .select_related("hospital")
            .get(pk=medicine_id)
        )
    except Medicine.DoesNotExist:
        raise ValidationError(
            {"medicine": "Medicine does not exist or is deleted."}
        ) from None

    locked_assignment = _locked_assignment(pharmacist_assignment)
    _validate_order_assignment(
        locked_item.order,
        locked_assignment,
    )

    if locked_item.order.status not in PROCESSABLE_ORDER_STATUSES:
        raise ValidationError(
            {
                "order_item": (
                    "The order must be accepted before assigning medicine."
                )
            }
        )

    order_hospital_id = locked_item.order.pharmacy.branch.hospital_id

    if locked_medicine.hospital_id != order_hospital_id:
        raise ValidationError(
            {
                "medicine": (
                    "The medicine and pharmacy must belong "
                    "to the same hospital."
                )
            }
        )

    if not locked_medicine.is_active:
        raise ValidationError(
            {"medicine": "The selected medicine is inactive."}
        )

    inventory = (
        PharmacyInventory.objects.select_for_update(of=("self",))
        .filter(
            pharmacy=locked_item.order.pharmacy,
            medicine=locked_medicine,
            is_active=True,
        )
        .first()
    )

    locked_item.medicine = locked_medicine
    locked_item.requested_unit = locked_medicine.dispensing_unit
    locked_item.is_substitution = bool(is_substitution)
    locked_item.pharmacist_notes = (notes or "").strip()
    locked_item.status = (
        PharmacyOrderItem.Status.AVAILABLE
        if inventory and inventory.quantity_on_hand > 0
        else PharmacyOrderItem.Status.UNAVAILABLE
    )
    locked_item.save()

    return locked_item


def _normalize_allocations(
    allocations: Iterable[Mapping[str, Any]],
) -> dict[tuple[int, int], int]:
    normalized: dict[tuple[int, int], int] = defaultdict(int)
    rows = list(allocations or [])

    if not rows:
        raise ValidationError(
            {"allocations": "At least one stock allocation is required."}
        )

    for row in rows:
        if not isinstance(row, Mapping):
            raise ValidationError(
                {"allocations": "Each allocation must be a mapping."}
            )

        order_item_value = row.get("order_item")
        stock_batch_value = row.get("stock_batch")

        if order_item_value is None:
            order_item_value = row.get("order_item_id")

        if stock_batch_value is None:
            stock_batch_value = row.get("stock_batch_id")

        order_item_id = _object_pk(order_item_value, "order_item")
        stock_batch_id = _object_pk(stock_batch_value, "stock_batch")

        try:
            quantity = int(row.get("quantity"))
        except (TypeError, ValueError) as exc:
            raise ValidationError(
                {"quantity": "Dispensed quantity must be an integer."}
            ) from exc

        if quantity < 1:
            raise ValidationError(
                {"quantity": "Dispensed quantity must be greater than zero."}
            )

        normalized[(order_item_id, stock_batch_id)] += quantity

    return dict(normalized)


def _base_item_status(item: PharmacyOrderItem) -> str:
    if not item.medicine_id:
        return PharmacyOrderItem.Status.PENDING

    inventory = PharmacyInventory.objects.filter(
        pharmacy=item.order.pharmacy,
        medicine_id=item.medicine_id,
        is_active=True,
    ).first()

    if inventory and inventory.quantity_on_hand > 0:
        return PharmacyOrderItem.Status.AVAILABLE

    return PharmacyOrderItem.Status.UNAVAILABLE


def _refresh_order_progress(order: PharmacyOrder) -> PharmacyOrder:
    items = list(
        PharmacyOrderItem.objects.select_for_update(of=("self",))
        .select_related(
            "order",
            "order__pharmacy",
            "medicine",
        )
        .filter(order=order)
        .order_by("id")
    )

    quantities: dict[int, int] = {}

    for item in items:
        dispensed_quantity = item.dispensed_quantity
        quantities[item.pk] = dispensed_quantity

        if dispensed_quantity >= item.requested_quantity:
            new_status = (
                PharmacyOrderItem.Status.SUBSTITUTED
                if item.is_substitution
                else PharmacyOrderItem.Status.DISPENSED
            )
        elif dispensed_quantity > 0:
            new_status = PharmacyOrderItem.Status.PARTIAL
        else:
            new_status = _base_item_status(item)

        if item.status != new_status:
            item.status = new_status
            item.save()

    all_completed = bool(items) and all(
        quantities[item.pk] >= item.requested_quantity
        for item in items
    )
    any_dispensed = any(
        quantity > 0 for quantity in quantities.values()
    )

    if all_completed:
        order.status = PharmacyOrder.Status.DISPENSED
    elif any_dispensed:
        order.status = PharmacyOrder.Status.PARTIALLY_DISPENSED
        order.completed_at = None
    else:
        order.status = PharmacyOrder.Status.IN_PROGRESS
        order.completed_at = None

    order.save()
    return order


@transaction.atomic
def complete_order_dispense(
    *,
    order: PharmacyOrder | int,
    pharmacist_assignment: PharmacyStaffAssignment | int,
    allocations: Iterable[Mapping[str, Any]],
    notes: str = "",
) -> Dispense:
    locked_order = _locked_order(order)
    locked_assignment = _locked_assignment(pharmacist_assignment)

    _validate_order_assignment(locked_order, locked_assignment)

    if locked_order.status not in PROCESSABLE_ORDER_STATUSES:
        raise ValidationError(
            {"order": "The order must be accepted before dispensing."}
        )

    normalized_allocations = _normalize_allocations(allocations)
    order_item_ids = {
        item_id for item_id, _batch_id in normalized_allocations
    }
    stock_batch_ids = {
        batch_id for _item_id, batch_id in normalized_allocations
    }

    order_items = {
        item.pk: item
        for item in (
            PharmacyOrderItem.objects.select_for_update(of=("self",))
            .select_related("order", "medicine")
            .filter(
                pk__in=order_item_ids,
                order=locked_order,
            )
        )
    }

    if len(order_items) != len(order_item_ids):
        raise ValidationError(
            {
                "allocations": (
                    "One or more order items do not belong "
                    "to this pharmacy order."
                )
            }
        )

    stock_batches = {
        batch.pk: batch
        for batch in (
            StockBatch.objects.select_for_update(of=("self",))
            .select_related(
                "inventory",
                "inventory__medicine",
                "inventory__pharmacy",
            )
            .filter(pk__in=stock_batch_ids)
        )
    }

    if len(stock_batches) != len(stock_batch_ids):
        raise ValidationError(
            {
                "allocations": (
                    "One or more stock batches do not exist or are deleted."
                )
            }
        )

    requested_by_item: dict[int, int] = defaultdict(int)
    requested_by_batch: dict[int, int] = defaultdict(int)

    for (
        order_item_id,
        stock_batch_id,
    ), quantity in normalized_allocations.items():
        item = order_items[order_item_id]
        batch = stock_batches[stock_batch_id]

        if not item.medicine_id:
            raise ValidationError(
                {
                    "order_item": (
                        f"Order item #{item.pk} has no linked medicine."
                    )
                }
            )

        if batch.inventory.pharmacy_id != locked_order.pharmacy_id:
            raise ValidationError(
                {"stock_batch": "The stock batch belongs to another pharmacy."}
            )

        if batch.inventory.medicine_id != item.medicine_id:
            raise ValidationError(
                {
                    "stock_batch": (
                        "The stock batch medicine does not match "
                        "the order item medicine."
                    )
                }
            )

        if not batch.is_active or batch.is_deleted:
            raise ValidationError(
                {"stock_batch": "The stock batch is inactive."}
            )

        if batch.expiry_date < timezone.localdate():
            raise ValidationError(
                {"stock_batch": "Expired stock cannot be dispensed."}
            )

        requested_by_item[order_item_id] += quantity
        requested_by_batch[stock_batch_id] += quantity

    for item_id, requested_quantity in requested_by_item.items():
        item = order_items[item_id]

        if requested_quantity > item.remaining_quantity:
            raise ValidationError(
                {
                    "quantity": (
                        f"Order item #{item.pk} has only "
                        f"{item.remaining_quantity} remaining."
                    )
                }
            )

    for batch_id, requested_quantity in requested_by_batch.items():
        batch = stock_batches[batch_id]

        if requested_quantity > batch.quantity_on_hand:
            raise ValidationError(
                {
                    "quantity": (
                        f"Batch {batch.batch_number} has only "
                        f"{batch.quantity_on_hand} units available."
                    )
                }
            )

    if not locked_order.assigned_to_id:
        locked_order.assigned_to = locked_assignment

    if locked_order.status == PharmacyOrder.Status.ACCEPTED:
        locked_order.status = PharmacyOrder.Status.IN_PROGRESS
        locked_order.save()

    dispense = Dispense.objects.create(
        order=locked_order,
        dispensed_by=locked_assignment,
        status=Dispense.Status.DRAFT,
        notes=(notes or "").strip(),
    )

    total_amount = Decimal("0.00")

    for (
        order_item_id,
        stock_batch_id,
    ), quantity in sorted(
        normalized_allocations.items(),
        key=lambda entry: (entry[0][1], entry[0][0]),
    ):
        item = order_items[order_item_id]
        batch = stock_batches[stock_batch_id]
        balance_before = batch.quantity_on_hand
        balance_after = balance_before - quantity
        unit_price = batch.selling_price

        dispense_item = DispenseItem.objects.create(
            dispense=dispense,
            order_item=item,
            stock_batch=batch,
            quantity=quantity,
            unit_price=unit_price,
        )

        batch.quantity_on_hand = balance_after
        batch.save()

        StockMovement.objects.create(
            stock_batch=batch,
            movement_type=StockMovement.Types.DISPENSE,
            quantity=quantity,
            balance_before=balance_before,
            balance_after=balance_after,
            dispense_item=dispense_item,
            created_by=locked_assignment.user,
            notes=(
                f"Dispense #{dispense.pk}, "
                f"pharmacy order #{locked_order.pk}."
            ),
        )

        total_amount += unit_price * quantity

    dispense.total_amount = total_amount
    dispense.status = Dispense.Status.COMPLETED
    dispense.dispensed_at = timezone.now()
    dispense.save()

    refreshed_order = _refresh_order_progress(locked_order)

    if refreshed_order.status == PharmacyOrder.Status.DISPENSED:
        prescription = refreshed_order.prescription
        doctor_user = getattr(
            getattr(prescription, "doctor", None),
            "user",
            None,
        )

        if doctor_user:
            patient_name = (
                getattr(prescription, "patient_full_name", "")
                or "the patient"
            )

            Notification.objects.create(
                recipient=doctor_user,
                notification_type=Notification.Types.PHARMACY,
                title="Prescription Dispensed",
                message=(
                    f"Prescription #{prescription.pk} for "
                    f"{patient_name} was dispensed by "
                    f"{refreshed_order.pharmacy.name}."
                ),
                action_url=prescription.get_absolute_url(),
            )

    return dispense


@transaction.atomic
def void_completed_dispense(
    *,
    dispense: Dispense | int,
    pharmacist_assignment: PharmacyStaffAssignment | int,
    reason: str,
) -> Dispense:
    dispense_id = _object_pk(dispense, "dispense")

    try:
        locked_dispense = (
            Dispense.objects.select_for_update(of=("self",))
            .select_related(
                "order",
                "order__pharmacy",
                "dispensed_by",
            )
            .get(pk=dispense_id)
        )
    except Dispense.DoesNotExist:
        raise ValidationError(
            {"dispense": "Dispense record does not exist."}
        ) from None

    locked_order = _locked_order(locked_dispense.order_id)
    locked_assignment = _locked_assignment(pharmacist_assignment)

    _validate_order_assignment(locked_order, locked_assignment)

    void_reason = (reason or "").strip()

    if not void_reason:
        raise ValidationError(
            {"reason": "A void reason is required."}
        )

    if locked_dispense.status != Dispense.Status.COMPLETED:
        raise ValidationError(
            {"dispense": "Only a completed dispense can be voided."}
        )

    dispense_items = list(
        DispenseItem.objects.select_for_update(of=("self",))
        .select_related("stock_batch", "stock_batch__inventory")
        .filter(dispense=locked_dispense)
        .order_by("id")
    )

    batch_ids = {item.stock_batch_id for item in dispense_items}
    stock_batches = {
        batch.pk: batch
        for batch in (
            StockBatch.objects.select_for_update(of=("self",))
            .filter(pk__in=batch_ids)
        )
    }

    for item in dispense_items:
        batch = stock_batches[item.stock_batch_id]
        balance_before = batch.quantity_on_hand
        balance_after = balance_before + item.quantity

        batch.quantity_on_hand = balance_after
        batch.save()

        StockMovement.objects.create(
            stock_batch=batch,
            movement_type=StockMovement.Types.PATIENT_RETURN,
            quantity=item.quantity,
            balance_before=balance_before,
            balance_after=balance_after,
            created_by=locked_assignment.user,
            notes=(
                f"Void dispense #{locked_dispense.pk}. "
                f"Reason: {void_reason}"
            ),
        )

    previous_notes = (locked_dispense.notes or "").strip()
    locked_dispense.notes = (
        f"{previous_notes}\nVoided: {void_reason}"
    ).strip()
    locked_dispense.status = Dispense.Status.VOIDED
    locked_dispense.save()

    _refresh_order_progress(locked_order)
    return locked_dispense


def _normalize_direct_sale_items(
    items: Iterable[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    rows = list(items or [])

    if not rows:
        raise ValidationError(
            {"items": "At least one medicine is required for a sale."}
        )

    normalized: list[dict[str, Any]] = []
    medicine_ids: set[int] = set()

    for index, row in enumerate(rows, start=1):
        if not isinstance(row, Mapping):
            raise ValidationError(
                {"items": f"Sale item #{index} must be a mapping."}
            )

        medicine_value = row.get("medicine")
        if medicine_value is None:
            medicine_value = row.get("medicine_id")

        medicine_id = _object_pk(medicine_value, "medicine")

        if medicine_id in medicine_ids:
            raise ValidationError(
                {
                    "items": (
                        "Each medicine can appear only once in a direct "
                        "sale. Increase the quantity on the existing line."
                    )
                }
            )

        try:
            quantity = int(row.get("quantity"))
        except (TypeError, ValueError) as exc:
            raise ValidationError(
                {
                    "quantity": (
                        f"Quantity for sale item #{index} must be an integer."
                    )
                }
            ) from exc

        if quantity < 1:
            raise ValidationError(
                {
                    "quantity": (
                        f"Quantity for sale item #{index} must be "
                        "greater than zero."
                    )
                }
            )

        raw_unit_price = row.get("unit_price")
        unit_price = (
            None
            if raw_unit_price in {None, ""}
            else _money(raw_unit_price, "unit_price")
        )

        discount_amount = _money(
            row.get("discount_amount", Decimal("0.00")),
            "discount_amount",
        )

        normalized.append(
            {
                "medicine_id": medicine_id,
                "quantity": quantity,
                "unit_price": unit_price,
                "discount_amount": discount_amount,
                "notes": (row.get("notes") or "").strip(),
            }
        )
        medicine_ids.add(medicine_id)

    return sorted(
        normalized,
        key=lambda row: row["medicine_id"],
    )


def _resolve_sale_payment(
    *,
    total_amount: Decimal,
    amount_paid: Any,
    payment_method: str,
    transaction_reference: str,
) -> tuple[Decimal, str, str, str]:
    paid = _money(amount_paid, "amount_paid")

    if paid > total_amount:
        raise ValidationError(
            {
                "amount_paid": (
                    "The paid amount cannot exceed the sale total."
                )
            }
        )

    method = (payment_method or "").strip()
    reference = (transaction_reference or "").strip()
    valid_methods = {
        value for value, _label in PharmacySale.PaymentMethod.choices
    }

    if paid == Decimal("0.00"):
        return (
            paid,
            PharmacySale.PaymentStatus.UNPAID,
            "",
            "",
        )

    if method not in valid_methods:
        raise ValidationError(
            {"payment_method": "A valid payment method is required."}
        )

    if method in {
        PharmacySale.PaymentMethod.CARD,
        PharmacySale.PaymentMethod.BANK_TRANSFER,
    } and not reference:
        raise ValidationError(
            {
                "transaction_reference": (
                    "A transaction reference is required for card "
                    "and bank transfer payments."
                )
            }
        )

    payment_status = (
        PharmacySale.PaymentStatus.PAID
        if paid == total_amount
        else PharmacySale.PaymentStatus.PARTIALLY_PAID
    )

    return paid, payment_status, method, reference


@transaction.atomic
def create_direct_sale(
    *,
    pharmacy: Pharmacy | int,
    cashier_assignment: PharmacyStaffAssignment | int,
    items: Iterable[Mapping[str, Any]],
    customer_name: str = "",
    customer_phone: str = "",
    discount_amount: Any = Decimal("0.00"),
    amount_paid: Any | None = None,
    payment_method: str = PharmacySale.PaymentMethod.CASH,
    transaction_reference: str = "",
    notes: str = "",
) -> PharmacySale:
    """
    Complete a walk-in POS sale and deduct stock using FEFO.

    This workflow is available to both integrated and standalone pharmacies.
    The earliest non-expired batches are consumed first. The whole operation
    is atomic, so a validation or stock error leaves inventory unchanged.
    """
    locked_pharmacy = _locked_pharmacy(pharmacy)
    locked_assignment = _locked_assignment(cashier_assignment)

    _validate_pharmacy(locked_pharmacy)
    _validate_pharmacist_assignment(
        locked_assignment,
        locked_pharmacy.pk,
    )

    normalized_items = _normalize_direct_sale_items(items)
    medicine_ids = {
        row["medicine_id"] for row in normalized_items
    }

    medicines = {
        medicine.pk: medicine
        for medicine in (
            Medicine.objects.select_for_update(of=("self",))
            .filter(pk__in=medicine_ids)
            .order_by("pk")
        )
    }

    if len(medicines) != len(medicine_ids):
        raise ValidationError(
            {
                "items": (
                    "One or more medicines do not exist or are deleted."
                )
            }
        )

    inventories = {
        inventory.medicine_id: inventory
        for inventory in (
            PharmacyInventory.objects.select_for_update(of=("self",))
            .select_related("medicine", "pharmacy")
            .filter(
                pharmacy=locked_pharmacy,
                medicine_id__in=medicine_ids,
                is_active=True,
            )
            .order_by("medicine_id")
        )
    }

    sale_lines: list[dict[str, Any]] = []
    subtotal = Decimal("0.00")
    today = timezone.localdate()

    for row in normalized_items:
        medicine = medicines[row["medicine_id"]]

        if not medicine.is_active:
            raise ValidationError(
                {
                    "medicine": (
                        f"{medicine.display_name} is inactive."
                    )
                }
            )

        if medicine.hospital_id != locked_pharmacy.branch.hospital_id:
            raise ValidationError(
                {
                    "medicine": (
                        f"{medicine.display_name} does not belong to "
                        "this pharmacy organization."
                    )
                }
            )

        inventory = inventories.get(medicine.pk)
        if not inventory:
            raise ValidationError(
                {
                    "inventory": (
                        f"{medicine.display_name} is not registered "
                        "in this pharmacy inventory."
                    )
                }
            )

        batches = list(
            StockBatch.objects.select_for_update(of=("self",))
            .filter(
                inventory=inventory,
                is_active=True,
                expiry_date__gte=today,
                quantity_on_hand__gt=0,
            )
            .order_by("expiry_date", "received_at", "pk")
        )

        available_quantity = sum(
            batch.quantity_on_hand for batch in batches
        )

        if available_quantity < row["quantity"]:
            raise ValidationError(
                {
                    "quantity": (
                        f"{medicine.display_name} has only "
                        f"{available_quantity} available units."
                    )
                }
            )

        remaining = row["quantity"]
        batch_allocations: list[tuple[StockBatch, int]] = []

        for batch in batches:
            if remaining == 0:
                break

            allocated = min(remaining, batch.quantity_on_hand)
            batch_allocations.append((batch, allocated))
            remaining -= allocated

        unit_price = row["unit_price"]
        if unit_price is None:
            unit_price = batch_allocations[0][0].selling_price
            unit_price = _money(unit_price, "unit_price")

        gross_amount = (
            unit_price * row["quantity"]
        ).quantize(MONEY_PLACES, rounding=ROUND_HALF_UP)
        item_discount = row["discount_amount"]

        if item_discount > gross_amount:
            raise ValidationError(
                {
                    "discount_amount": (
                        f"The discount for {medicine.display_name} "
                        "cannot exceed its gross amount."
                    )
                }
            )

        line_total = gross_amount - item_discount
        subtotal += line_total

        sale_lines.append(
            {
                **row,
                "medicine": medicine,
                "inventory": inventory,
                "unit_price": unit_price,
                "allocations": batch_allocations,
            }
        )

    subtotal = subtotal.quantize(
        MONEY_PLACES,
        rounding=ROUND_HALF_UP,
    )
    sale_discount = _money(
        discount_amount,
        "discount_amount",
    )

    if sale_discount > subtotal:
        raise ValidationError(
            {
                "discount_amount": (
                    "The sale discount cannot exceed the subtotal."
                )
            }
        )

    total_amount = (subtotal - sale_discount).quantize(
        MONEY_PLACES,
        rounding=ROUND_HALF_UP,
    )

    if total_amount <= Decimal("0.00"):
        raise ValidationError(
            {
                "total_amount": (
                    "A completed direct sale must have a positive total."
                )
            }
        )

    raw_paid = total_amount if amount_paid is None else amount_paid
    (
        paid,
        payment_status,
        clean_payment_method,
        clean_reference,
    ) = _resolve_sale_payment(
        total_amount=total_amount,
        amount_paid=raw_paid,
        payment_method=payment_method,
        transaction_reference=transaction_reference,
    )

    sale = PharmacySale.objects.create(
        pharmacy=locked_pharmacy,
        cashier=locked_assignment,
        customer_name=customer_name,
        customer_phone=customer_phone,
        status=PharmacySale.Status.COMPLETED,
        subtotal=subtotal,
        discount_amount=sale_discount,
        total_amount=total_amount,
        amount_paid=paid,
        payment_status=payment_status,
        payment_method=clean_payment_method,
        transaction_reference=clean_reference,
        notes=(notes or "").strip(),
        completed_at=timezone.now(),
    )

    for line in sale_lines:
        sale_item = PharmacySaleItem.objects.create(
            sale=sale,
            medicine=line["medicine"],
            quantity=line["quantity"],
            unit_price=line["unit_price"],
            discount_amount=line["discount_amount"],
            notes=line["notes"],
        )

        for batch, allocated_quantity in line["allocations"]:
            balance_before = batch.quantity_on_hand
            balance_after = balance_before - allocated_quantity

            allocation = PharmacySaleAllocation.objects.create(
                sale_item=sale_item,
                stock_batch=batch,
                quantity=allocated_quantity,
                unit_purchase_price=batch.purchase_price,
            )

            batch.quantity_on_hand = balance_after
            batch.save(update_fields=["quantity_on_hand", "updated_at"])

            StockMovement.objects.create(
                stock_batch=batch,
                movement_type=StockMovement.Types.DIRECT_SALE,
                quantity=allocated_quantity,
                balance_before=balance_before,
                balance_after=balance_after,
                direct_sale_allocation=allocation,
                created_by=locked_assignment.user,
                notes=(
                    f"Direct sale {sale.sale_number}; "
                    f"medicine {line['medicine'].display_name}."
                ),
            )

    return sale


@transaction.atomic
def record_direct_sale_payment(
    *,
    sale: PharmacySale | int,
    cashier_assignment: PharmacyStaffAssignment | int,
    amount: Any,
    payment_method: str,
    transaction_reference: str = "",
    notes: str = "",
) -> PharmacySale:
    locked_sale = _locked_sale(sale)
    locked_assignment = _locked_assignment(cashier_assignment)

    _validate_pharmacist_assignment(
        locked_assignment,
        locked_sale.pharmacy_id,
    )

    if locked_sale.status != PharmacySale.Status.COMPLETED:
        raise ValidationError(
            {"sale": "Payments can only be recorded for a completed sale."}
        )

    if locked_sale.balance_due <= Decimal("0.00"):
        raise ValidationError(
            {"sale": "This direct sale is already fully paid."}
        )

    payment_amount = _money(
        amount,
        "amount",
        allow_zero=False,
    )

    if payment_amount > locked_sale.balance_due:
        raise ValidationError(
            {
                "amount": (
                    "The payment cannot exceed the outstanding balance."
                )
            }
        )

    new_amount_paid = (
        locked_sale.amount_paid + payment_amount
    ).quantize(MONEY_PLACES, rounding=ROUND_HALF_UP)

    (
        _paid,
        payment_status,
        clean_method,
        clean_reference,
    ) = _resolve_sale_payment(
        total_amount=locked_sale.total_amount,
        amount_paid=new_amount_paid,
        payment_method=payment_method,
        transaction_reference=transaction_reference,
    )

    payment_note = (
        f"Payment {payment_amount:.2f} recorded by "
        f"{locked_assignment.user}."
    )
    extra_note = (notes or "").strip()
    if extra_note:
        payment_note = f"{payment_note} {extra_note}"

    locked_sale.amount_paid = new_amount_paid
    locked_sale.payment_status = payment_status
    locked_sale.payment_method = clean_method
    locked_sale.transaction_reference = clean_reference
    locked_sale.notes = (
        f"{locked_sale.notes}\n{payment_note}"
    ).strip()
    locked_sale.save()

    return locked_sale


@transaction.atomic
def void_direct_sale(
    *,
    sale: PharmacySale | int,
    pharmacist_assignment: PharmacyStaffAssignment | int,
    reason: str,
    voided_by: Any | None = None,
) -> PharmacySale:
    locked_sale = _locked_sale(sale)
    locked_assignment = _locked_assignment(pharmacist_assignment)

    _validate_pharmacist_assignment(
        locked_assignment,
        locked_sale.pharmacy_id,
    )

    void_reason = (reason or "").strip()
    if not void_reason:
        raise ValidationError(
            {"reason": "A reason is required to void a direct sale."}
        )

    if locked_sale.status == PharmacySale.Status.VOIDED:
        return locked_sale

    if locked_sale.status != PharmacySale.Status.COMPLETED:
        raise ValidationError(
            {"sale": "Only a completed direct sale can be voided."}
        )

    actor = voided_by or locked_assignment.user
    if not getattr(actor, "is_authenticated", False):
        raise ValidationError(
            {"voided_by": "An authenticated user is required."}
        )

    allocations = list(
        PharmacySaleAllocation.objects.select_for_update(of=("self",))
        .select_related(
            "sale_item",
            "stock_batch",
            "stock_batch__inventory",
        )
        .filter(sale_item__sale=locked_sale)
        .order_by("stock_batch_id", "pk")
    )

    batch_ids = {
        allocation.stock_batch_id for allocation in allocations
    }
    stock_batches = {
        batch.pk: batch
        for batch in (
            StockBatch.objects.select_for_update(of=("self",))
            .filter(pk__in=batch_ids)
            .order_by("pk")
        )
    }

    for allocation in allocations:
        batch = stock_batches[allocation.stock_batch_id]
        balance_before = batch.quantity_on_hand
        balance_after = balance_before + allocation.quantity

        batch.quantity_on_hand = balance_after
        batch.save(update_fields=["quantity_on_hand", "updated_at"])

        StockMovement.objects.create(
            stock_batch=batch,
            movement_type=StockMovement.Types.PATIENT_RETURN,
            quantity=allocation.quantity,
            balance_before=balance_before,
            balance_after=balance_after,
            direct_sale_allocation=allocation,
            created_by=actor,
            notes=(
                f"Void direct sale {locked_sale.sale_number}. "
                f"Reason: {void_reason}"
            ),
        )

    locked_sale.status = PharmacySale.Status.VOIDED
    locked_sale.voided_by = actor
    locked_sale.voided_at = timezone.now()
    locked_sale.notes = (
        f"{locked_sale.notes}\nVoided: {void_reason}"
    ).strip()
    locked_sale.save()

    return locked_sale
