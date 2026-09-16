from __future__ import annotations

from decimal import Decimal
from typing import Any

from django import forms
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from prescription.models import Prescription

from .access import accessible_pharmacies, active_pharmacy_assignments
from .models import (
    Dispense,
    Medicine,
    Pharmacy,
    PharmacyInventory,
    PharmacyOrder,
    PharmacyOrderItem,
    PharmacySale,
    StockBatch,
    StockMovement,
)


class BootstrapFormMixin:
    def _apply_bootstrap(self) -> None:
        for field in self.fields.values():
            widget = field.widget
            if isinstance(widget, forms.CheckboxInput):
                widget.attrs["class"] = "form-check-input"
            elif isinstance(widget, (forms.Select, forms.SelectMultiple)):
                widget.attrs["class"] = "form-select"
            else:
                widget.attrs["class"] = "form-control"


class StandalonePharmacySetupForm(
    BootstrapFormMixin,
    forms.Form,
):
    name = forms.CharField(
        label="Pharmacy name",
        max_length=200,
    )
    code = forms.CharField(
        label="Pharmacy code",
        max_length=24,
        help_text="A unique short code, for example: ALHAYAT.",
    )
    phone = forms.CharField(
        label="Phone",
        max_length=30,
        required=False,
    )
    email = forms.EmailField(
        label="Email",
        required=False,
    )
    address = forms.CharField(
        label="Address",
        required=False,
        widget=forms.Textarea(attrs={"rows": 3}),
    )
    license_number = forms.CharField(
        label="License number",
        max_length=100,
        required=False,
    )

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._apply_bootstrap()

    def clean_name(self) -> str:
        name = " ".join(
            (self.cleaned_data.get("name") or "").split()
        ).strip()
        if not name:
            raise ValidationError("Pharmacy name is required.")
        return name

    def clean_code(self) -> str:
        code = (
            self.cleaned_data.get("code") or ""
        ).strip().upper()
        if not code:
            raise ValidationError("Pharmacy code is required.")
        if not code.replace("-", "").replace("_", "").isalnum():
            raise ValidationError(
                "Use letters, numbers, hyphens or underscores only."
            )
        return code

    def save(self, *, owner_user: Any):
        if not self.is_valid():
            raise ValueError(
                "The standalone pharmacy form must be valid before saving."
            )

        from .services import create_standalone_pharmacy

        return create_standalone_pharmacy(
            name=self.cleaned_data["name"],
            code=self.cleaned_data["code"],
            owner_user=owner_user,
            phone=self.cleaned_data.get("phone", ""),
            email=self.cleaned_data.get("email", ""),
            address=self.cleaned_data.get("address", ""),
            license_number=self.cleaned_data.get(
                "license_number",
                "",
            ),
        )


class MedicineManagementForm(BootstrapFormMixin, forms.ModelForm):
    """
    Create or edit a hospital medicine and optionally add it to one
    pharmacy inventory.

    The hospital is never accepted from browser input. It is derived from
    the selected pharmacy, which prevents a pharmacist from creating a
    medicine under an unrelated hospital or standalone organization.
    """

    pharmacy = forms.ModelChoiceField(
        queryset=Pharmacy.objects.none(),
        empty_label="Select a pharmacy",
        help_text=(
            "The medicine will belong to this pharmacy's hospital or "
            "standalone organization."
        ),
    )
    add_to_inventory = forms.BooleanField(
        label="Add to this pharmacy inventory",
        required=False,
        initial=True,
        help_text=(
            "Creates the inventory record now. Stock quantities are "
            "received later from the Receive stock page."
        ),
    )
    reorder_level = forms.IntegerField(
        label="Reorder level",
        min_value=0,
        required=False,
        initial=10,
        help_text="Show a low-stock warning at or below this quantity.",
    )
    target_stock = forms.IntegerField(
        label="Target stock",
        min_value=0,
        required=False,
        initial=100,
        help_text="Preferred quantity after restocking.",
    )

    class Meta:
        model = Medicine
        fields = [
            "code",
            "barcode",
            "generic_name",
            "brand_name",
            "strength",
            "dosage_form",
            "dispensing_unit",
            "manufacturer",
            "description",
            "requires_prescription",
            "is_controlled",
            "is_active",
        ]
        widgets = {
            "description": forms.Textarea(attrs={"rows": 4}),
        }
        help_texts = {
            "code": "Unique inside the selected hospital or organization.",
            "barcode": "Optional, but must be unique when entered.",
            "generic_name": "The active ingredient, for example Paracetamol.",
            "brand_name": "Commercial name, for example Panadol.",
            "strength": "For example 500 mg or 125 mg/5 ml.",
            "dispensing_unit": "For example tablet, capsule, bottle, vial or tube.",
        }

    def __init__(
        self,
        *args,
        pharmacies,
        **kwargs,
    ) -> None:
        super().__init__(*args, **kwargs)
        self.fields["pharmacy"].queryset = pharmacies.select_related(
            "branch",
            "branch__hospital",
        ).order_by(
            "branch__hospital__name",
            "branch__name",
            "name",
        )

        self.order_fields(
            [
                "pharmacy",
                "code",
                "barcode",
                "generic_name",
                "brand_name",
                "strength",
                "dosage_form",
                "dispensing_unit",
                "manufacturer",
                "description",
                "requires_prescription",
                "is_controlled",
                "is_active",
                "add_to_inventory",
                "reorder_level",
                "target_stock",
            ]
        )

        if not self.is_bound:
            selected_pharmacy = None
            if self.instance and self.instance.pk:
                selected_pharmacy = (
                    PharmacyInventory.objects.filter(
                        medicine=self.instance,
                        pharmacy__in=pharmacies,
                        is_deleted=False,
                    )
                    .select_related("pharmacy")
                    .order_by("-is_active", "pharmacy__name")
                    .first()
                )
                if selected_pharmacy:
                    inventory = selected_pharmacy
                    self.initial.update(
                        {
                            "pharmacy": inventory.pharmacy_id,
                            "add_to_inventory": True,
                            "reorder_level": inventory.reorder_level,
                            "target_stock": inventory.target_stock,
                        }
                    )
                else:
                    first_pharmacy = pharmacies.first()
                    if first_pharmacy:
                        self.initial["pharmacy"] = first_pharmacy.pk
            else:
                first_pharmacy = pharmacies.first()
                if first_pharmacy:
                    self.initial["pharmacy"] = first_pharmacy.pk

        self._apply_bootstrap()

    def clean(self) -> dict[str, Any]:
        cleaned = super().clean()
        pharmacy = cleaned.get("pharmacy")
        code = (cleaned.get("code") or "").strip().upper()
        barcode = (cleaned.get("barcode") or "").strip()
        add_to_inventory = cleaned.get("add_to_inventory", False)
        reorder_level = cleaned.get("reorder_level")
        target_stock = cleaned.get("target_stock")

        cleaned["code"] = code
        cleaned["barcode"] = barcode

        if pharmacy and self.instance and self.instance.pk:
            if self.instance.hospital_id != pharmacy.branch.hospital_id:
                self.add_error(
                    "pharmacy",
                    (
                        "An existing medicine cannot be moved to a "
                        "different hospital or organization."
                    ),
                )

        if pharmacy and code:
            duplicate_code = Medicine.all_objects.filter(
                hospital_id=pharmacy.branch.hospital_id,
                code__iexact=code,
                is_deleted=False,
            )
            if self.instance and self.instance.pk:
                duplicate_code = duplicate_code.exclude(pk=self.instance.pk)
            if duplicate_code.exists():
                self.add_error(
                    "code",
                    "This medicine code already exists for the selected pharmacy.",
                )

        if pharmacy and barcode:
            duplicate_barcode = Medicine.all_objects.filter(
                hospital_id=pharmacy.branch.hospital_id,
                barcode=barcode,
                is_deleted=False,
            )
            if self.instance and self.instance.pk:
                duplicate_barcode = duplicate_barcode.exclude(
                    pk=self.instance.pk
                )
            if duplicate_barcode.exists():
                self.add_error(
                    "barcode",
                    "This barcode already exists for the selected pharmacy.",
                )

        if add_to_inventory:
            if reorder_level is None:
                self.add_error(
                    "reorder_level",
                    "Enter the reorder level.",
                )
            if target_stock is None:
                self.add_error(
                    "target_stock",
                    "Enter the target stock.",
                )
            if (
                reorder_level is not None
                and target_stock is not None
                and target_stock < reorder_level
            ):
                self.add_error(
                    "target_stock",
                    "Target stock cannot be lower than the reorder level.",
                )

        return cleaned

    @transaction.atomic
    def save(self, commit: bool = True) -> Medicine:
        if not hasattr(self, "cleaned_data"):
            raise ValueError(
                "The medicine form must be validated before saving."
            )

        pharmacy = self.cleaned_data["pharmacy"]
        medicine = super().save(commit=False)

        if not medicine.pk:
            medicine.hospital = pharmacy.branch.hospital

        if not commit:
            return medicine

        medicine.save()
        self.save_m2m()

        if self.cleaned_data.get("add_to_inventory"):
            inventory, created = PharmacyInventory.objects.get_or_create(
                pharmacy=pharmacy,
                medicine=medicine,
                defaults={
                    "reorder_level": self.cleaned_data["reorder_level"],
                    "target_stock": self.cleaned_data["target_stock"],
                    "is_active": True,
                },
            )
            if not created:
                inventory.reorder_level = self.cleaned_data[
                    "reorder_level"
                ]
                inventory.target_stock = self.cleaned_data["target_stock"]
                inventory.is_active = True
                inventory.save(
                    update_fields=[
                        "reorder_level",
                        "target_stock",
                        "is_active",
                        "updated_at",
                    ]
                )

        return medicine


class SendPrescriptionToPharmacyForm(BootstrapFormMixin, forms.Form):
    pharmacy = forms.ModelChoiceField(
        queryset=Pharmacy.objects.none(),
        empty_label="Select a pharmacy",
    )
    priority = forms.ChoiceField(
        choices=PharmacyOrder.Priority.choices,
        initial=PharmacyOrder.Priority.NORMAL,
    )
    doctor_notes = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={"rows": 4}),
        help_text="Optional notes for the pharmacy team.",
    )

    def __init__(
        self,
        *args,
        prescription: Prescription,
        **kwargs,
    ) -> None:
        super().__init__(*args, **kwargs)
        self.prescription = prescription

        pharmacies = Pharmacy.objects.filter(
            operating_mode=Pharmacy.OperatingModes.INTEGRATED,
            is_active=True,
            is_deleted=False,
            branch__is_active=True,
            branch__is_deleted=False,
            branch__hospital__is_active=True,
            branch__hospital__is_deleted=False,
        ).select_related("branch", "branch__hospital")

        branch_id = getattr(prescription.appointment, "branch_id", None)
        if branch_id:
            hospital_id = prescription.appointment.branch.hospital_id
            pharmacies = pharmacies.filter(branch__hospital_id=hospital_id)

        self.fields["pharmacy"].queryset = pharmacies.order_by(
            "branch__hospital__name",
            "branch__name",
            "name",
        )
        self._apply_bootstrap()


class RejectOrderForm(BootstrapFormMixin, forms.Form):
    reason = forms.CharField(
        label="Rejection reason",
        widget=forms.Textarea(attrs={"rows": 4}),
    )

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._apply_bootstrap()


class VoidDispenseForm(BootstrapFormMixin, forms.Form):
    reason = forms.CharField(
        label="Void reason",
        widget=forms.Textarea(attrs={"rows": 4}),
    )

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._apply_bootstrap()


class AssignMedicineForm(BootstrapFormMixin, forms.Form):
    medicine = forms.ModelChoiceField(
        queryset=Medicine.objects.none(),
        empty_label="Select a medicine",
    )
    requested_quantity = forms.IntegerField(min_value=1, initial=1)
    requested_unit = forms.CharField(max_length=30, initial="unit")
    is_substitution = forms.BooleanField(required=False)
    notes = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={"rows": 3}),
    )

    def __init__(
        self,
        *args,
        order_item: PharmacyOrderItem,
        **kwargs,
    ) -> None:
        super().__init__(*args, **kwargs)
        self.order_item = order_item
        hospital_id = order_item.order.pharmacy.branch.hospital_id

        self.fields["medicine"].queryset = Medicine.objects.filter(
            hospital_id=hospital_id,
            is_active=True,
            is_deleted=False,
        ).order_by("generic_name", "brand_name", "strength")

        if not self.is_bound:
            self.initial.update(
                {
                    "medicine": order_item.medicine_id,
                    "requested_quantity": order_item.requested_quantity,
                    "requested_unit": order_item.requested_unit,
                    "is_substitution": order_item.is_substitution,
                    "notes": order_item.pharmacist_notes,
                }
            )

        self._apply_bootstrap()

    def clean(self) -> dict[str, Any]:
        cleaned = super().clean()
        medicine = cleaned.get("medicine")
        requested_quantity = cleaned.get("requested_quantity")
        already_dispensed = self.order_item.dispensed_quantity

        if (
            requested_quantity is not None
            and requested_quantity < already_dispensed
        ):
            self.add_error(
                "requested_quantity",
                f"Quantity cannot be lower than the {already_dispensed} units already dispensed.",
            )

        if (
            already_dispensed > 0
            and medicine
            and self.order_item.medicine_id
            and medicine.pk != self.order_item.medicine_id
        ):
            self.add_error(
                "medicine",
                "The medicine cannot be changed after dispensing has started.",
            )

        return cleaned


class StockBatchChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, obj: StockBatch) -> str:
        return (
            f"{obj.batch_number} | Exp: {obj.expiry_date:%Y-%m-%d} | "
            f"Available: {obj.quantity_on_hand} | Price: {obj.selling_price}"
        )


class DispenseOrderForm(BootstrapFormMixin, forms.Form):
    payment_status = forms.ChoiceField(
        label="Payment status",
        choices=[
            (
                Dispense.PaymentStatus.UNPAID,
                Dispense.PaymentStatus.UNPAID.label,
            ),
            (
                Dispense.PaymentStatus.PARTIALLY_PAID,
                Dispense.PaymentStatus.PARTIALLY_PAID.label,
            ),
            (
                Dispense.PaymentStatus.PAID,
                Dispense.PaymentStatus.PAID.label,
            ),
        ],
        initial=Dispense.PaymentStatus.UNPAID,
        required=False,
    )
    payment_method = forms.ChoiceField(
        label="Payment method",
        choices=[
            ("", "Select payment method"),
            *Dispense.PaymentMethod.choices,
        ],
        required=False,
    )
    amount_paid = forms.DecimalField(
        label="Amount paid",
        min_value=Decimal("0.00"),
        max_digits=14,
        decimal_places=2,
        initial=Decimal("0.00"),
        required=False,
    )
    received_by_name = forms.CharField(
        label="Received by",
        max_length=200,
        required=False,
        help_text="Patient or representative receiving the medicines.",
    )
    transaction_reference = forms.CharField(
        label="Transaction reference",
        max_length=100,
        required=False,
        help_text="Required for card or bank transfer payments.",
    )
    notes = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={"rows": 3}),
    )

    def __init__(
        self,
        *args,
        order: PharmacyOrder,
        **kwargs,
    ) -> None:
        super().__init__(*args, **kwargs)
        self.order = order
        self.dispensable_items: list[PharmacyOrderItem] = []
        self.calculated_total = Decimal("0.00")

        patient = getattr(order.prescription, "patient", None)
        if patient is None:
            appointment = getattr(order.prescription, "appointment", None)
            patient = getattr(appointment, "patient", None)

        patient_name = getattr(patient, "full_name", "")
        if patient_name and not self.is_bound:
            self.fields["received_by_name"].initial = patient_name

        items = order.items.select_related("medicine").order_by("id")
        for item in items:
            if not item.medicine_id or item.remaining_quantity < 1:
                continue

            self.dispensable_items.append(item)
            batches = StockBatch.objects.filter(
                inventory__pharmacy=order.pharmacy,
                inventory__medicine_id=item.medicine_id,
                inventory__is_active=True,
                inventory__is_deleted=False,
                is_active=True,
                is_deleted=False,
                quantity_on_hand__gt=0,
                expiry_date__gte=timezone.localdate(),
            ).select_related("inventory", "inventory__medicine").order_by(
                "expiry_date",
                "received_at",
                "id",
            )

            self.fields[f"batch_{item.pk}"] = StockBatchChoiceField(
                label=f"Batch for {item.medication_name}",
                queryset=batches,
                required=False,
                empty_label="Do not dispense this item",
            )
            self.fields[f"quantity_{item.pk}"] = forms.IntegerField(
                label=f"Quantity for {item.medication_name}",
                min_value=0,
                max_value=item.remaining_quantity,
                initial=0,
                required=False,
                help_text=f"Remaining prescribed quantity: {item.remaining_quantity}",
            )

        self._apply_bootstrap()

    def clean(self) -> dict[str, Any]:
        cleaned = super().clean()
        has_allocation = False
        calculated_total = Decimal("0.00")

        for item in self.dispensable_items:
            batch = cleaned.get(f"batch_{item.pk}")
            quantity = cleaned.get(f"quantity_{item.pk}") or 0

            if quantity > 0 and not batch:
                self.add_error(
                    f"batch_{item.pk}",
                    "Select a stock batch for this quantity.",
                )
            if batch and quantity < 1:
                self.add_error(
                    f"quantity_{item.pk}",
                    "Enter a quantity greater than zero.",
                )
            if batch and quantity > batch.quantity_on_hand:
                self.add_error(
                    f"quantity_{item.pk}",
                    f"Only {batch.quantity_on_hand} units are available in this batch.",
                )
            if batch and quantity > 0:
                has_allocation = True
                calculated_total += Decimal(quantity) * batch.selling_price

        if not has_allocation:
            raise ValidationError("Select at least one item and quantity to dispense.")

        calculated_total = calculated_total.quantize(Decimal("0.01"))
        self.calculated_total = calculated_total

        payment_status = (
            cleaned.get("payment_status")
            or Dispense.PaymentStatus.UNPAID
        )
        cleaned["payment_status"] = payment_status
        payment_method = cleaned.get("payment_method") or ""
        amount_paid = cleaned.get("amount_paid") or Decimal("0.00")
        transaction_reference = (
            cleaned.get("transaction_reference") or ""
        ).strip()
        cleaned["transaction_reference"] = transaction_reference

        if amount_paid > calculated_total:
            self.add_error(
                "amount_paid",
                f"The paid amount cannot exceed the total amount of {calculated_total}.",
            )

        if payment_status == Dispense.PaymentStatus.UNPAID:
            if amount_paid != Decimal("0.00"):
                self.add_error(
                    "amount_paid",
                    "An unpaid dispense must have a paid amount of zero.",
                )
        elif payment_status == Dispense.PaymentStatus.PARTIALLY_PAID:
            if not Decimal("0.00") < amount_paid < calculated_total:
                self.add_error(
                    "amount_paid",
                    "For partial payment, the paid amount must be greater than zero and lower than the total.",
                )
            if not payment_method:
                self.add_error("payment_method", "Select a payment method.")
        elif payment_status == Dispense.PaymentStatus.PAID:
            if amount_paid != calculated_total:
                self.add_error(
                    "amount_paid",
                    f"For a paid dispense, the paid amount must equal {calculated_total}.",
                )
            if not payment_method:
                self.add_error("payment_method", "Select a payment method.")

        if (
            payment_method
            in {
                Dispense.PaymentMethod.CARD,
                Dispense.PaymentMethod.BANK_TRANSFER,
            }
            and not transaction_reference
        ):
            self.add_error(
                "transaction_reference",
                "Enter the transaction reference for card or bank transfer payments.",
            )

        return cleaned

    def allocations(self) -> list[dict[str, Any]]:
        if not hasattr(self, "cleaned_data"):
            return []

        result = []
        for item in self.dispensable_items:
            batch = self.cleaned_data.get(f"batch_{item.pk}")
            quantity = self.cleaned_data.get(f"quantity_{item.pk}") or 0
            if batch and quantity > 0:
                result.append(
                    {
                        "order_item": item,
                        "stock_batch": batch,
                        "quantity": quantity,
                    }
                )
        return result

    def payment_data(self) -> dict[str, Any]:
        if not hasattr(self, "cleaned_data"):
            return {}

        return {
            "total_amount": self.calculated_total,
            "amount_paid": self.cleaned_data.get(
                "amount_paid",
                Decimal("0.00"),
            ),
            "payment_status": self.cleaned_data.get(
                "payment_status",
                Dispense.PaymentStatus.UNPAID,
            ),
            "payment_method": self.cleaned_data.get("payment_method", ""),
            "transaction_reference": self.cleaned_data.get(
                "transaction_reference",
                "",
            ),
            "received_by_name": self.cleaned_data.get(
                "received_by_name",
                "",
            ),
            "notes": self.cleaned_data.get("notes", ""),
        }


class RecordPaymentForm(BootstrapFormMixin, forms.Form):
    amount_received = forms.DecimalField(
        label="Amount received now",
        min_value=Decimal("0.01"),
        max_digits=14,
        decimal_places=2,
        help_text="Enter only the amount received in this payment.",
    )
    payment_method = forms.ChoiceField(
        label="Payment method",
        choices=[
            ("", "Select payment method"),
            *Dispense.PaymentMethod.choices,
        ],
    )
    transaction_reference = forms.CharField(
        label="Transaction reference",
        max_length=100,
        required=False,
        help_text="Required for card and bank transfer payments.",
    )
    received_by_name = forms.CharField(
        label="Received by",
        max_length=200,
        required=False,
        help_text="Patient or representative receiving the medicines.",
    )
    notes = forms.CharField(
        label="Payment notes",
        required=False,
        widget=forms.Textarea(attrs={"rows": 3}),
    )

    def __init__(
        self,
        *args,
        dispense: Dispense,
        **kwargs,
    ) -> None:
        super().__init__(*args, **kwargs)
        self.dispense = dispense

        balance_due = Decimal(dispense.balance_due).quantize(
            Decimal("0.01")
        )
        amount_field = self.fields["amount_received"]
        amount_field.max_value = balance_due
        amount_field.widget.attrs.update(
            {
                "min": "0.01",
                "max": str(balance_due),
                "step": "0.01",
            }
        )
        amount_field.help_text = (
            f"Outstanding balance: {balance_due:.2f} IQD."
        )

        if not self.is_bound:
            amount_field.initial = balance_due
            self.fields["received_by_name"].initial = (
                dispense.received_by_name
            )

        self._apply_bootstrap()

    def clean(self) -> dict[str, Any]:
        cleaned = super().clean()
        balance_due = Decimal(self.dispense.balance_due).quantize(
            Decimal("0.01")
        )
        amount_received = cleaned.get("amount_received")
        payment_method = cleaned.get("payment_method") or ""
        transaction_reference = (
            cleaned.get("transaction_reference") or ""
        ).strip()
        received_by_name = (
            cleaned.get("received_by_name") or ""
        ).strip()

        cleaned["transaction_reference"] = transaction_reference
        cleaned["received_by_name"] = received_by_name

        if self.dispense.status == Dispense.Status.VOIDED:
            raise ValidationError(
                "Payment cannot be recorded for a voided dispense."
            )

        if balance_due <= Decimal("0.00"):
            raise ValidationError("This dispense is already fully paid.")

        if amount_received is not None and amount_received > balance_due:
            self.add_error(
                "amount_received",
                f"The payment cannot exceed the outstanding balance of {balance_due:.2f} IQD.",
            )

        if (
            payment_method
            in {
                Dispense.PaymentMethod.CARD,
                Dispense.PaymentMethod.BANK_TRANSFER,
            }
            and not transaction_reference
        ):
            self.add_error(
                "transaction_reference",
                "Enter the transaction reference for card or bank transfer payments.",
            )

        return cleaned

    def updated_amount_paid(self) -> Decimal:
        current_amount = self.dispense.amount_paid or Decimal("0.00")
        received_amount = self.cleaned_data.get(
            "amount_received",
            Decimal("0.00"),
        )
        return (current_amount + received_amount).quantize(
            Decimal("0.01")
        )

    def resulting_payment_status(self) -> str:
        updated_amount = self.updated_amount_paid()
        total_amount = (
            self.dispense.total_amount or Decimal("0.00")
        ).quantize(Decimal("0.01"))

        if updated_amount >= total_amount:
            return Dispense.PaymentStatus.PAID
        if updated_amount > Decimal("0.00"):
            return Dispense.PaymentStatus.PARTIALLY_PAID
        return Dispense.PaymentStatus.UNPAID

    def payment_data(self) -> dict[str, Any]:
        if not hasattr(self, "cleaned_data"):
            return {}

        return {
            "amount_received": self.cleaned_data.get(
                "amount_received",
                Decimal("0.00"),
            ),
            "amount_paid": self.updated_amount_paid(),
            "payment_status": self.resulting_payment_status(),
            "payment_method": self.cleaned_data.get(
                "payment_method",
                "",
            ),
            "transaction_reference": self.cleaned_data.get(
                "transaction_reference",
                "",
            ),
            "received_by_name": self.cleaned_data.get(
                "received_by_name",
                "",
            ),
            "notes": self.cleaned_data.get("notes", ""),
        }


class DirectSaleForm(BootstrapFormMixin, forms.Form):
    pharmacy = forms.ModelChoiceField(
        label="Pharmacy",
        queryset=Pharmacy.objects.none(),
        empty_label="Select a pharmacy",
    )
    customer_name = forms.CharField(
        label="Customer name",
        max_length=200,
        required=False,
    )
    customer_phone = forms.CharField(
        label="Customer phone",
        max_length=30,
        required=False,
    )
    discount_amount = forms.DecimalField(
        label="Sale discount",
        min_value=Decimal("0.00"),
        max_digits=14,
        decimal_places=2,
        initial=Decimal("0.00"),
        required=False,
        help_text="An optional discount applied to the whole sale.",
    )
    amount_paid = forms.DecimalField(
        label="Amount paid",
        min_value=Decimal("0.00"),
        max_digits=14,
        decimal_places=2,
        required=False,
        help_text=(
            "Leave blank to mark the full sale amount as paid. "
            "Enter zero to save it as unpaid."
        ),
    )
    payment_method = forms.ChoiceField(
        label="Payment method",
        choices=[
            ("", "Select payment method"),
            *PharmacySale.PaymentMethod.choices,
        ],
        initial=PharmacySale.PaymentMethod.CASH,
        required=False,
    )
    transaction_reference = forms.CharField(
        label="Transaction reference",
        max_length=100,
        required=False,
        help_text="Required for card and bank transfer payments.",
    )
    notes = forms.CharField(
        label="Sale notes",
        required=False,
        widget=forms.Textarea(attrs={"rows": 3}),
    )

    def __init__(
        self,
        *args,
        user: Any,
        pharmacy: Pharmacy | None = None,
        **kwargs,
    ) -> None:
        super().__init__(*args, **kwargs)
        self.user = user

        pharmacies = (
            accessible_pharmacies(user)
            .filter(
                is_active=True,
                is_deleted=False,
                branch__is_active=True,
                branch__is_deleted=False,
                branch__hospital__is_active=True,
                branch__hospital__is_deleted=False,
            )
            .select_related("branch", "branch__hospital")
            .order_by(
                "operating_mode",
                "branch__hospital__name",
                "name",
            )
        )
        self.fields["pharmacy"].queryset = pharmacies

        if pharmacy and not self.is_bound:
            self.fields["pharmacy"].initial = pharmacy

        self._apply_bootstrap()

    @property
    def selected_pharmacy(self) -> Pharmacy | None:
        if hasattr(self, "cleaned_data"):
            return self.cleaned_data.get("pharmacy")

        pharmacy_value = self.data.get(
            self.add_prefix("pharmacy")
        )
        if pharmacy_value:
            try:
                return self.fields["pharmacy"].queryset.get(
                    pk=pharmacy_value
                )
            except (
                Pharmacy.DoesNotExist,
                TypeError,
                ValueError,
            ):
                return None

        initial = self.initial.get(
            "pharmacy",
            self.fields["pharmacy"].initial,
        )
        if isinstance(initial, Pharmacy):
            return initial
        if initial:
            try:
                return self.fields["pharmacy"].queryset.get(pk=initial)
            except (
                Pharmacy.DoesNotExist,
                TypeError,
                ValueError,
            ):
                return None
        return None

    def clean(self) -> dict[str, Any]:
        cleaned = super().clean()
        amount_paid = cleaned.get("amount_paid")
        payment_method = cleaned.get("payment_method") or ""
        transaction_reference = (
            cleaned.get("transaction_reference") or ""
        ).strip()

        cleaned["transaction_reference"] = transaction_reference
        cleaned["customer_name"] = " ".join(
            (cleaned.get("customer_name") or "").split()
        ).strip()
        cleaned["customer_phone"] = (
            cleaned.get("customer_phone") or ""
        ).strip()

        if (
            amount_paid is not None
            and amount_paid > Decimal("0.00")
            and not payment_method
        ):
            self.add_error(
                "payment_method",
                "Select a payment method for a paid amount.",
            )

        if (
            amount_paid is None
            and not payment_method
        ):
            self.add_error(
                "payment_method",
                (
                    "Select a payment method because a blank amount "
                    "means full payment."
                ),
            )

        if (
            payment_method
            in {
                PharmacySale.PaymentMethod.CARD,
                PharmacySale.PaymentMethod.BANK_TRANSFER,
            }
            and amount_paid != Decimal("0.00")
            and not transaction_reference
        ):
            self.add_error(
                "transaction_reference",
                (
                    "Enter the transaction reference for card or "
                    "bank transfer payments."
                ),
            )

        return cleaned

    def service_data(self) -> dict[str, Any]:
        if not hasattr(self, "cleaned_data"):
            return {}

        return {
            "pharmacy": self.cleaned_data["pharmacy"],
            "customer_name": self.cleaned_data.get(
                "customer_name",
                "",
            ),
            "customer_phone": self.cleaned_data.get(
                "customer_phone",
                "",
            ),
            "discount_amount": self.cleaned_data.get(
                "discount_amount",
                Decimal("0.00"),
            )
            or Decimal("0.00"),
            "amount_paid": self.cleaned_data.get("amount_paid"),
            "payment_method": self.cleaned_data.get(
                "payment_method",
                "",
            ),
            "transaction_reference": self.cleaned_data.get(
                "transaction_reference",
                "",
            ),
            "notes": self.cleaned_data.get("notes", ""),
        }


class DirectSaleItemForm(BootstrapFormMixin, forms.Form):
    medicine = forms.ModelChoiceField(
        label="Medicine",
        queryset=Medicine.objects.none(),
        empty_label="Select a medicine",
    )
    quantity = forms.IntegerField(
        label="Quantity",
        min_value=1,
        initial=1,
    )
    unit_price = forms.DecimalField(
        label="Unit price",
        min_value=Decimal("0.00"),
        max_digits=14,
        decimal_places=2,
        required=False,
        help_text=(
            "Leave blank to use the selling price of the first FEFO batch."
        ),
    )
    discount_amount = forms.DecimalField(
        label="Item discount",
        min_value=Decimal("0.00"),
        max_digits=14,
        decimal_places=2,
        initial=Decimal("0.00"),
        required=False,
    )
    notes = forms.CharField(
        label="Item notes",
        required=False,
        widget=forms.Textarea(attrs={"rows": 2}),
    )

    def __init__(
        self,
        *args,
        pharmacy: Pharmacy | None = None,
        **kwargs,
    ) -> None:
        super().__init__(*args, **kwargs)
        self.pharmacy = pharmacy

        if pharmacy:
            self.fields["medicine"].queryset = (
                Medicine.objects.filter(
                    hospital_id=pharmacy.branch.hospital_id,
                    is_active=True,
                    is_deleted=False,
                    pharmacy_inventory__pharmacy=pharmacy,
                    pharmacy_inventory__is_active=True,
                    pharmacy_inventory__is_deleted=False,
                    pharmacy_inventory__batches__is_active=True,
                    pharmacy_inventory__batches__is_deleted=False,
                    pharmacy_inventory__batches__quantity_on_hand__gt=0,
                    pharmacy_inventory__batches__expiry_date__gte=(
                        timezone.localdate()
                    ),
                )
                .distinct()
                .order_by(
                    "generic_name",
                    "brand_name",
                    "strength",
                )
            )

        self._apply_bootstrap()

    def clean(self) -> dict[str, Any]:
        cleaned = super().clean()
        medicine = cleaned.get("medicine")
        quantity = cleaned.get("quantity")
        unit_price = cleaned.get("unit_price")
        discount = (
            cleaned.get("discount_amount")
            or Decimal("0.00")
        )

        if medicine and self.pharmacy:
            if medicine.hospital_id != self.pharmacy.branch.hospital_id:
                self.add_error(
                    "medicine",
                    "The medicine does not belong to this pharmacy.",
                )

        if (
            quantity
            and unit_price is not None
            and discount > unit_price * quantity
        ):
            self.add_error(
                "discount_amount",
                "The item discount cannot exceed its gross amount.",
            )

        return cleaned

    def service_data(self) -> dict[str, Any]:
        if not hasattr(self, "cleaned_data"):
            return {}

        return {
            "medicine": self.cleaned_data["medicine"],
            "quantity": self.cleaned_data["quantity"],
            "unit_price": self.cleaned_data.get("unit_price"),
            "discount_amount": self.cleaned_data.get(
                "discount_amount",
                Decimal("0.00"),
            )
            or Decimal("0.00"),
            "notes": self.cleaned_data.get("notes", ""),
        }


class BaseDirectSaleItemFormSet(forms.BaseFormSet):
    def __init__(
        self,
        *args,
        pharmacy: Pharmacy | None = None,
        **kwargs,
    ) -> None:
        self.pharmacy = pharmacy
        super().__init__(*args, **kwargs)

    def get_form_kwargs(self, index):
        kwargs = super().get_form_kwargs(index)
        kwargs["pharmacy"] = self.pharmacy
        return kwargs

    def clean(self) -> None:
        super().clean()

        if any(self.errors):
            return

        selected_medicines: set[int] = set()
        has_item = False

        for form in self.forms:
            if not hasattr(form, "cleaned_data"):
                continue

            if self.can_delete and form.cleaned_data.get("DELETE"):
                continue

            medicine = form.cleaned_data.get("medicine")
            if not medicine:
                continue

            has_item = True
            if medicine.pk in selected_medicines:
                form.add_error(
                    "medicine",
                    (
                        "This medicine is already included. Increase "
                        "the quantity on the existing row."
                    ),
                )
            selected_medicines.add(medicine.pk)

        if not has_item:
            raise ValidationError(
                "Add at least one medicine to the direct sale."
            )

    def items_data(self) -> list[dict[str, Any]]:
        if not self.is_valid():
            return []

        result: list[dict[str, Any]] = []
        for form in self.forms:
            if self.can_delete and form.cleaned_data.get("DELETE"):
                continue
            if not form.cleaned_data.get("medicine"):
                continue
            result.append(form.service_data())
        return result


DirectSaleItemFormSet = forms.formset_factory(
    DirectSaleItemForm,
    formset=BaseDirectSaleItemFormSet,
    extra=1,
    can_delete=True,
    min_num=1,
    validate_min=True,
)


class DirectSalePaymentForm(BootstrapFormMixin, forms.Form):
    amount = forms.DecimalField(
        label="Amount received now",
        min_value=Decimal("0.01"),
        max_digits=14,
        decimal_places=2,
    )
    payment_method = forms.ChoiceField(
        label="Payment method",
        choices=[
            ("", "Select payment method"),
            *PharmacySale.PaymentMethod.choices,
        ],
    )
    transaction_reference = forms.CharField(
        label="Transaction reference",
        max_length=100,
        required=False,
        help_text="Required for card and bank transfer payments.",
    )
    notes = forms.CharField(
        label="Payment notes",
        required=False,
        widget=forms.Textarea(attrs={"rows": 3}),
    )

    def __init__(
        self,
        *args,
        sale: PharmacySale,
        **kwargs,
    ) -> None:
        super().__init__(*args, **kwargs)
        self.sale = sale
        balance_due = Decimal(sale.balance_due).quantize(
            Decimal("0.01")
        )

        amount_field = self.fields["amount"]
        amount_field.max_value = balance_due
        amount_field.widget.attrs.update(
            {
                "min": "0.01",
                "max": str(balance_due),
                "step": "0.01",
            }
        )
        amount_field.help_text = (
            f"Outstanding balance: {balance_due:.2f} IQD."
        )

        if not self.is_bound and balance_due > Decimal("0.00"):
            amount_field.initial = balance_due

        self._apply_bootstrap()

    def clean(self) -> dict[str, Any]:
        cleaned = super().clean()
        amount = cleaned.get("amount")
        method = cleaned.get("payment_method") or ""
        reference = (
            cleaned.get("transaction_reference") or ""
        ).strip()
        balance_due = Decimal(self.sale.balance_due).quantize(
            Decimal("0.01")
        )
        cleaned["transaction_reference"] = reference

        if self.sale.status != PharmacySale.Status.COMPLETED:
            raise ValidationError(
                "Payments can only be recorded for a completed sale."
            )

        if balance_due <= Decimal("0.00"):
            raise ValidationError("This sale is already fully paid.")

        if amount is not None and amount > balance_due:
            self.add_error(
                "amount",
                (
                    "The payment cannot exceed the outstanding "
                    f"balance of {balance_due:.2f} IQD."
                ),
            )

        if (
            method
            in {
                PharmacySale.PaymentMethod.CARD,
                PharmacySale.PaymentMethod.BANK_TRANSFER,
            }
            and not reference
        ):
            self.add_error(
                "transaction_reference",
                (
                    "Enter the transaction reference for card or "
                    "bank transfer payments."
                ),
            )

        return cleaned

    def service_data(self) -> dict[str, Any]:
        if not hasattr(self, "cleaned_data"):
            return {}

        return {
            "amount": self.cleaned_data["amount"],
            "payment_method": self.cleaned_data["payment_method"],
            "transaction_reference": self.cleaned_data.get(
                "transaction_reference",
                "",
            ),
            "notes": self.cleaned_data.get("notes", ""),
        }


class VoidDirectSaleForm(BootstrapFormMixin, forms.Form):
    reason = forms.CharField(
        label="Void reason",
        widget=forms.Textarea(attrs={"rows": 4}),
    )

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._apply_bootstrap()

    def clean_reason(self) -> str:
        reason = (
            self.cleaned_data.get("reason") or ""
        ).strip()
        if not reason:
            raise ValidationError("A void reason is required.")
        return reason


class StockReceiptForm(BootstrapFormMixin, forms.Form):
    inventory = forms.ModelChoiceField(
        queryset=PharmacyInventory.objects.none(),
        empty_label="Select an inventory item",
    )
    batch_number = forms.CharField(max_length=100)
    expiry_date = forms.DateField(
        widget=forms.DateInput(attrs={"type": "date"}),
    )
    received_quantity = forms.IntegerField(min_value=1)
    purchase_price = forms.DecimalField(
        min_value=Decimal("0.00"),
        max_digits=14,
        decimal_places=2,
        initial=Decimal("0.00"),
    )
    selling_price = forms.DecimalField(
        min_value=Decimal("0.00"),
        max_digits=14,
        decimal_places=2,
        initial=Decimal("0.00"),
    )
    supplier_name = forms.CharField(max_length=200, required=False)

    def __init__(self, *args, user: Any, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        pharmacy_ids = accessible_pharmacies(user).values_list("id", flat=True)
        self.fields["inventory"].queryset = (
            PharmacyInventory.objects.filter(
                pharmacy_id__in=pharmacy_ids,
                pharmacy__is_active=True,
                medicine__is_active=True,
                is_active=True,
                is_deleted=False,
            )
            .select_related("pharmacy", "medicine")
            .order_by("pharmacy__name", "medicine__generic_name")
        )
        self._apply_bootstrap()

    def clean_expiry_date(self):
        expiry_date = self.cleaned_data["expiry_date"]
        if expiry_date < timezone.localdate():
            raise ValidationError("An expired batch cannot be received.")
        return expiry_date

    @transaction.atomic
    def save(self, *, user: Any) -> StockBatch:
        if not self.is_valid():
            raise ValueError("The stock receipt form must be valid before saving.")

        inventory = self.cleaned_data["inventory"]
        allowed = active_pharmacy_assignments(user).filter(
            pharmacy_id=inventory.pharmacy_id,
        ).exists()
        if not allowed:
            raise ValidationError("You are not assigned to this pharmacy.")

        quantity = self.cleaned_data["received_quantity"]
        batch = StockBatch.objects.create(
            inventory=inventory,
            batch_number=self.cleaned_data["batch_number"],
            expiry_date=self.cleaned_data["expiry_date"],
            received_quantity=quantity,
            quantity_on_hand=quantity,
            purchase_price=self.cleaned_data["purchase_price"],
            selling_price=self.cleaned_data["selling_price"],
            supplier_name=self.cleaned_data["supplier_name"],
            is_active=True,
        )

        StockMovement.objects.create(
            stock_batch=batch,
            movement_type=StockMovement.Types.RECEIPT,
            quantity=quantity,
            balance_before=0,
            balance_after=quantity,
            created_by=user,
            notes=f"Initial receipt for batch {batch.batch_number}.",
        )
        return batch
