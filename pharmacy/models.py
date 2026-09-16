from __future__ import annotations

from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import Q, Sum
from django.db.models.functions import Coalesce
from django.utils import timezone

from core.models import SoftDeleteModel


class Pharmacy(SoftDeleteModel):
    class OperatingModes(models.TextChoices):
        INTEGRATED = "integrated", "Integrated with Hospital"
        STANDALONE = "standalone", "Standalone Pharmacy"

    class Types(models.TextChoices):
        OUTPATIENT = "outpatient", "Outpatient"
        INPATIENT = "inpatient", "Inpatient"
        EMERGENCY = "emergency", "Emergency"
        CENTRAL = "central", "Central"

    branch = models.ForeignKey(
        "hospital.Branch",
        on_delete=models.PROTECT,
        related_name="pharmacies",
    )
    name = models.CharField(max_length=200)
    code = models.CharField(max_length=30)
    operating_mode = models.CharField(
        max_length=20,
        choices=OperatingModes.choices,
        default=OperatingModes.INTEGRATED,
        db_index=True,
        help_text=(
            "Integrated pharmacies receive hospital prescriptions. "
            "Standalone pharmacies use direct POS sales and a "
            "system-managed administrative branch."
        ),
    )
    pharmacy_type = models.CharField(
        max_length=20,
        choices=Types.choices,
        default=Types.OUTPATIENT,
        db_index=True,
    )
    phone = models.CharField(max_length=30, blank=True)
    email = models.EmailField(blank=True)
    location = models.CharField(max_length=255, blank=True)
    license_number = models.CharField(max_length=100, blank=True)
    is_active = models.BooleanField(default=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["branch_id", "name"]
        indexes = [
            models.Index(
                fields=["branch", "is_active"],
                name="pharm_branch_active_idx",
            ),
            models.Index(
                fields=["operating_mode", "is_active"],
                name="pharm_mode_active_idx",
            ),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["branch", "code"],
                condition=Q(is_deleted=False),
                name="uq_pharmacy_branch_code",
            ),
        ]

    @property
    def hospital(self):
        return self.branch.hospital

    @property
    def is_integrated(self):
        return self.operating_mode == self.OperatingModes.INTEGRATED

    @property
    def is_standalone(self):
        return self.operating_mode == self.OperatingModes.STANDALONE

    def clean(self):
        super().clean()
        errors = {}

        if not (self.name or "").strip():
            errors["name"] = "Pharmacy name cannot be empty."
        if not (self.code or "").strip():
            errors["code"] = "Pharmacy code cannot be empty."
        if self.branch_id and not self.branch.is_active:
            errors["branch"] = "The selected branch is inactive."

        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.name = " ".join((self.name or "").split()).strip()
        self.code = (self.code or "").strip().upper()
        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.branch} - {self.name}"


class PharmacyStaffAssignment(SoftDeleteModel):
    pharmacy = models.ForeignKey(
        Pharmacy,
        on_delete=models.PROTECT,
        related_name="staff_assignments",
    )
    staff_assignment = models.ForeignKey(
        "hospital.StaffAssignment",
        on_delete=models.PROTECT,
        related_name="pharmacy_assignments",
    )
    is_manager = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True, db_index=True)
    start_date = models.DateField(null=True, blank=True)
    end_date = models.DateField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["pharmacy_id", "staff_assignment_id"]
        indexes = [
            models.Index(
                fields=["pharmacy", "is_active"],
                name="pharm_staff_active_idx",
            ),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["pharmacy", "staff_assignment"],
                condition=Q(is_deleted=False),
                name="uq_pharmacy_staff",
            ),
        ]

    @property
    def user(self):
        return self.staff_assignment.user

    def clean(self):
        super().clean()
        errors = {}

        if self.staff_assignment_id:
            assignment = self.staff_assignment

            if assignment.is_deleted or not assignment.is_active:
                errors["staff_assignment"] = "The hospital staff assignment is inactive."

            if assignment.role != "pharmacist":
                errors["staff_assignment"] = "The hospital staff assignment must have the pharmacist role."

            if getattr(assignment.user, "role", None) != "pharmacist":
                errors["staff_assignment"] = "The linked user must have the pharmacist account role."

            if self.pharmacy_id:
                if assignment.hospital_id != self.pharmacy.branch.hospital_id:
                    errors["staff_assignment"] = "The pharmacist and pharmacy must belong to the same hospital."
                elif assignment.branch_id and assignment.branch_id != self.pharmacy.branch_id:
                    errors["staff_assignment"] = "The pharmacist and pharmacy must belong to the same branch."

        if self.start_date and self.end_date and self.end_date < self.start_date:
            errors["end_date"] = "The end date cannot be earlier than the start date."

        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.user} | {self.pharmacy}"


class Medicine(SoftDeleteModel):
    class DosageForms(models.TextChoices):
        TABLET = "tablet", "Tablet"
        CAPSULE = "capsule", "Capsule"
        SYRUP = "syrup", "Syrup"
        SUSPENSION = "suspension", "Suspension"
        INJECTION = "injection", "Injection"
        CREAM = "cream", "Cream"
        OINTMENT = "ointment", "Ointment"
        DROPS = "drops", "Drops"
        INHALER = "inhaler", "Inhaler"
        SUPPOSITORY = "suppository", "Suppository"
        OTHER = "other", "Other"

    hospital = models.ForeignKey(
        "hospital.Hospital",
        on_delete=models.PROTECT,
        related_name="medicines",
    )
    code = models.CharField(max_length=50)
    barcode = models.CharField(max_length=100, blank=True)
    generic_name = models.CharField(max_length=200, db_index=True)
    brand_name = models.CharField(max_length=200, blank=True, db_index=True)
    strength = models.CharField(max_length=100, blank=True)
    dosage_form = models.CharField(
        max_length=20,
        choices=DosageForms.choices,
        default=DosageForms.TABLET,
        db_index=True,
    )
    dispensing_unit = models.CharField(
        max_length=30,
        default="unit",
        help_text="Examples: tablet, capsule, bottle, vial, tube.",
    )
    manufacturer = models.CharField(max_length=200, blank=True)
    description = models.TextField(blank=True)
    requires_prescription = models.BooleanField(default=True)
    is_controlled = models.BooleanField(default=False, db_index=True)
    is_active = models.BooleanField(default=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["generic_name", "brand_name", "strength"]
        indexes = [
            models.Index(
                fields=["hospital", "is_active"],
                name="med_hospital_active_idx",
            ),
            models.Index(
                fields=["generic_name", "brand_name"],
                name="med_names_idx",
            ),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["hospital", "code"],
                condition=Q(is_deleted=False),
                name="uq_medicine_hospital_code",
            ),
            models.UniqueConstraint(
                fields=["hospital", "barcode"],
                condition=Q(is_deleted=False) & ~Q(barcode=""),
                name="uq_medicine_hosp_barcode",
            ),
        ]

    @property
    def display_name(self):
        parts = [self.brand_name or self.generic_name, self.strength, self.get_dosage_form_display()]
        return " ".join(part for part in parts if part).strip()

    def clean(self):
        super().clean()
        errors = {}

        if not (self.code or "").strip():
            errors["code"] = "Medicine code cannot be empty."
        if not (self.generic_name or "").strip():
            errors["generic_name"] = "Generic name cannot be empty."
        if not (self.dispensing_unit or "").strip():
            errors["dispensing_unit"] = "Dispensing unit cannot be empty."

        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.code = (self.code or "").strip().upper()
        self.barcode = (self.barcode or "").strip()
        self.generic_name = " ".join((self.generic_name or "").split()).strip()
        self.brand_name = " ".join((self.brand_name or "").split()).strip()
        self.strength = " ".join((self.strength or "").split()).strip()
        self.dispensing_unit = " ".join((self.dispensing_unit or "").split()).strip().lower()
        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self):
        return self.display_name


class PharmacyInventory(SoftDeleteModel):
    pharmacy = models.ForeignKey(
        Pharmacy,
        on_delete=models.PROTECT,
        related_name="inventory_items",
    )
    medicine = models.ForeignKey(
        Medicine,
        on_delete=models.PROTECT,
        related_name="pharmacy_inventory",
    )
    reorder_level = models.PositiveIntegerField(default=0)
    target_stock = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["pharmacy_id", "medicine__generic_name"]
        indexes = [
            models.Index(
                fields=["pharmacy", "is_active"],
                name="inventory_pharm_active_idx",
            ),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["pharmacy", "medicine"],
                condition=Q(is_deleted=False),
                name="uq_pharmacy_inventory",
            ),
        ]

    @property
    def quantity_on_hand(self):
        today = timezone.localdate()
        result = self.batches.filter(
            is_active=True,
            expiry_date__gte=today,
        ).aggregate(
            total=Coalesce(Sum("quantity_on_hand"), 0),
        )
        return int(result["total"] or 0)

    @property
    def needs_reorder(self):
        return self.quantity_on_hand <= self.reorder_level

    def active_batches(self):
        return self.batches.filter(
            is_active=True,
            quantity_on_hand__gt=0,
            expiry_date__gte=timezone.localdate(),
        ).order_by("expiry_date", "received_at", "id")

    def clean(self):
        super().clean()
        errors = {}

        if self.pharmacy_id and self.medicine_id:
            if self.pharmacy.branch.hospital_id != self.medicine.hospital_id:
                errors["medicine"] = "The medicine and pharmacy must belong to the same hospital."

        if self.target_stock and self.target_stock < self.reorder_level:
            errors["target_stock"] = "Target stock cannot be lower than the reorder level."

        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.pharmacy} | {self.medicine}"


class StockBatch(SoftDeleteModel):
    inventory = models.ForeignKey(
        PharmacyInventory,
        on_delete=models.PROTECT,
        related_name="batches",
    )
    batch_number = models.CharField(max_length=100)
    expiry_date = models.DateField(db_index=True)
    received_quantity = models.PositiveIntegerField(default=0)
    quantity_on_hand = models.PositiveIntegerField(default=0)
    purchase_price = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=Decimal("0.00"),
        validators=[MinValueValidator(Decimal("0.00"))],
    )
    selling_price = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=Decimal("0.00"),
        validators=[MinValueValidator(Decimal("0.00"))],
    )
    supplier_name = models.CharField(max_length=200, blank=True)
    received_at = models.DateTimeField(default=timezone.now, db_index=True)
    is_active = models.BooleanField(default=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["expiry_date", "received_at", "id"]
        indexes = [
            models.Index(
                fields=["inventory", "expiry_date", "is_active"],
                name="batch_inventory_exp_idx",
            ),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["inventory", "batch_number"],
                condition=Q(is_deleted=False),
                name="uq_inventory_batch_number",
            ),
            models.CheckConstraint(
                condition=Q(received_quantity__gte=0),
                name="ck_batch_received_nonneg",
            ),
            models.CheckConstraint(
                condition=Q(quantity_on_hand__gte=0),
                name="ck_batch_on_hand_nonneg",
            ),
            models.CheckConstraint(
                condition=Q(purchase_price__gte=0),
                name="ck_batch_purchase_nonneg",
            ),
            models.CheckConstraint(
                condition=Q(selling_price__gte=0),
                name="ck_batch_selling_nonneg",
            ),
        ]

    @property
    def is_expired(self):
        return self.expiry_date < timezone.localdate()

    @property
    def is_available(self):
        return self.is_active and not self.is_deleted and not self.is_expired and self.quantity_on_hand > 0

    def clean(self):
        super().clean()
        errors = {}

        if not (self.batch_number or "").strip():
            errors["batch_number"] = "Batch number cannot be empty."
        if self.selling_price < 0:
            errors["selling_price"] = "Selling price cannot be negative."
        if self.purchase_price < 0:
            errors["purchase_price"] = "Purchase price cannot be negative."

        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.batch_number = (self.batch_number or "").strip().upper()
        self.supplier_name = " ".join((self.supplier_name or "").split()).strip()

        if self._state.adding and self.received_quantity and self.quantity_on_hand == 0:
            self.quantity_on_hand = self.received_quantity

        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.inventory.medicine} | Batch {self.batch_number}"


class PharmacyOrder(SoftDeleteModel):
    class Status(models.TextChoices):
        SENT = "sent", "Sent"
        ACCEPTED = "accepted", "Accepted"
        IN_PROGRESS = "in_progress", "In Progress"
        PARTIALLY_DISPENSED = "partial", "Partially Dispensed"
        DISPENSED = "dispensed", "Dispensed"
        REJECTED = "rejected", "Rejected"
        CANCELLED = "cancelled", "Cancelled"

    class Priority(models.TextChoices):
        NORMAL = "normal", "Normal"
        URGENT = "urgent", "Urgent"
        STAT = "stat", "STAT"

    prescription = models.ForeignKey(
        "prescription.Prescription",
        on_delete=models.PROTECT,
        related_name="pharmacy_orders",
    )
    pharmacy = models.ForeignKey(
        Pharmacy,
        on_delete=models.PROTECT,
        related_name="orders",
    )
    sent_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="pharmacy_orders_sent",
    )
    assigned_to = models.ForeignKey(
        PharmacyStaffAssignment,
        on_delete=models.PROTECT,
        related_name="assigned_orders",
        null=True,
        blank=True,
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.SENT,
        db_index=True,
    )
    priority = models.CharField(
        max_length=10,
        choices=Priority.choices,
        default=Priority.NORMAL,
        db_index=True,
    )
    doctor_notes = models.TextField(blank=True)
    pharmacy_notes = models.TextField(blank=True)
    rejection_reason = models.TextField(blank=True)
    sent_at = models.DateTimeField(default=timezone.now, db_index=True)
    accepted_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-priority", "sent_at", "id"]
        indexes = [
            models.Index(
                fields=["pharmacy", "status", "sent_at"],
                name="order_pharm_status_idx",
            ),
            models.Index(
                fields=["prescription", "status"],
                name="order_rx_status_idx",
            ),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["prescription"],
                condition=(
                    Q(is_deleted=False)
                    & Q(status__in=["sent", "accepted", "in_progress", "partial"])
                ),
                name="uq_active_prescription_order",
            ),
        ]

    def clean(self):
        super().clean()
        errors = {}

        if self.assigned_to_id:
            if self.assigned_to.pharmacy_id != self.pharmacy_id:
                errors["assigned_to"] = "The pharmacist must be assigned to the selected pharmacy."
            elif not self.assigned_to.is_active or self.assigned_to.is_deleted:
                errors["assigned_to"] = "The selected pharmacist assignment is inactive."

        if self.prescription_id and self.sent_by_id:
            doctor_user_id = getattr(getattr(self.prescription, "doctor", None), "user_id", None)
            if (
                self.sent_by_id != doctor_user_id
                and not getattr(self.sent_by, "is_superuser", False)
                and getattr(self.sent_by, "role", None) != "admin"
            ):
                errors["sent_by"] = "Only the prescribing doctor or an administrator can send this prescription."

        if self.status == self.Status.REJECTED and not (self.rejection_reason or "").strip():
            errors["rejection_reason"] = "A rejection reason is required."

        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        now = timezone.now()

        if self.status in {self.Status.ACCEPTED, self.Status.IN_PROGRESS} and not self.accepted_at:
            self.accepted_at = now
        if self.status == self.Status.DISPENSED and not self.completed_at:
            self.completed_at = now

        self.full_clean()
        super().save(*args, **kwargs)
        self._sync_prescription_status()

    def _sync_prescription_status(self):
        target_status = None

        if self.status in {
            self.Status.SENT,
            self.Status.ACCEPTED,
            self.Status.IN_PROGRESS,
            self.Status.PARTIALLY_DISPENSED,
        }:
            target_status = "sent"
        elif self.status == self.Status.DISPENSED:
            target_status = "completed"
        elif self.status in {self.Status.REJECTED, self.Status.CANCELLED}:
            target_status = "draft"

        if target_status and self.prescription.status != target_status:
            self.prescription.__class__.objects.filter(pk=self.prescription_id).update(
                status=target_status,
            )
            self.prescription.status = target_status

    def __str__(self):
        return f"Order #{self.pk} | Prescription #{self.prescription_id}"


class PharmacyOrderItem(SoftDeleteModel):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        AVAILABLE = "available", "Available"
        UNAVAILABLE = "unavailable", "Unavailable"
        PARTIAL = "partial", "Partially Available"
        DISPENSED = "dispensed", "Dispensed"
        SUBSTITUTED = "substituted", "Substituted"

    order = models.ForeignKey(
        PharmacyOrder,
        on_delete=models.PROTECT,
        related_name="items",
    )
    prescription_medication = models.ForeignKey(
        "prescription.Medication",
        on_delete=models.PROTECT,
        related_name="pharmacy_order_items",
    )
    medicine = models.ForeignKey(
        Medicine,
        on_delete=models.PROTECT,
        related_name="order_items",
        null=True,
        blank=True,
    )
    medication_name = models.CharField(max_length=200, blank=True)
    dosage = models.CharField(max_length=255, blank=True)
    requested_quantity = models.PositiveIntegerField(default=1)
    requested_unit = models.CharField(max_length=30, default="unit")
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
        db_index=True,
    )
    is_substitution = models.BooleanField(default=False)
    pharmacist_notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["order_id", "id"]
        indexes = [
            models.Index(
                fields=["order", "status"],
                name="order_item_status_idx",
            ),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["order", "prescription_medication"],
                condition=Q(is_deleted=False),
                name="uq_order_prescription_med",
            ),
            models.CheckConstraint(
                condition=Q(requested_quantity__gt=0),
                name="ck_order_item_quantity_pos",
            ),
        ]

    @property
    def dispensed_quantity(self):
        result = self.dispense_items.filter(
            dispense__status="completed",
        ).aggregate(total=Coalesce(Sum("quantity"), 0))
        return int(result["total"] or 0)

    @property
    def remaining_quantity(self):
        return max(self.requested_quantity - self.dispensed_quantity, 0)

    def clean(self):
        super().clean()
        errors = {}

        if self.order_id and self.prescription_medication_id:
            if self.prescription_medication.prescription_id != self.order.prescription_id:
                errors["prescription_medication"] = "The medication must belong to the order prescription."

        if self.order_id and self.medicine_id:
            if self.medicine.hospital_id != self.order.pharmacy.branch.hospital_id:
                errors["medicine"] = "The medicine and pharmacy must belong to the same hospital."

        if self.requested_quantity < 1:
            errors["requested_quantity"] = "Requested quantity must be greater than zero."

        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        if self.prescription_medication_id:
            if not (self.medication_name or "").strip():
                self.medication_name = self.prescription_medication.name
            if not (self.dosage or "").strip():
                self.dosage = self.prescription_medication.dosage

        self.medication_name = " ".join((self.medication_name or "").split()).strip()
        self.dosage = " ".join((self.dosage or "").split()).strip()
        self.requested_unit = " ".join((self.requested_unit or "").split()).strip().lower()
        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.medication_name} | Order #{self.order_id}"


class Dispense(SoftDeleteModel):
    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        COMPLETED = "completed", "Completed"
        VOIDED = "voided", "Voided"

    class PaymentStatus(models.TextChoices):
        UNPAID = "unpaid", "Unpaid"
        PARTIALLY_PAID = "partially_paid", "Partially Paid"
        PAID = "paid", "Paid"

    class PaymentMethod(models.TextChoices):
        CASH = "cash", "Cash"
        CARD = "card", "Card"
        BANK_TRANSFER = "bank_transfer", "Bank Transfer"
        INSURANCE = "insurance", "Insurance"
        OTHER = "other", "Other"

    order = models.ForeignKey(
        PharmacyOrder,
        on_delete=models.PROTECT,
        related_name="dispenses",
    )
    dispensed_by = models.ForeignKey(
        PharmacyStaffAssignment,
        on_delete=models.PROTECT,
        related_name="dispenses",
    )
    status = models.CharField(
        max_length=10,
        choices=Status.choices,
        default=Status.DRAFT,
        db_index=True,
    )
    total_amount = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=Decimal("0.00"),
        validators=[MinValueValidator(Decimal("0.00"))],
    )

    amount_paid = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=Decimal("0.00"),
        validators=[MinValueValidator(Decimal("0.00"))],
    )

    payment_status = models.CharField(
        max_length=20,
        choices=PaymentStatus.choices,
        default=PaymentStatus.UNPAID,
        db_index=True,
    )

    payment_method = models.CharField(
        max_length=20,
        choices=PaymentMethod.choices,
        blank=True,
        default="",
    )

    received_by_name = models.CharField(
        max_length=200,
        blank=True,
        default="",
    )

    transaction_reference = models.CharField(
        max_length=100,
        blank=True,
        default="",
    )

    notes = models.TextField(blank=True, default="")
    dispensed_at = models.DateTimeField(null=True, blank=True, db_index=True)
    paid_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [
            models.Index(
                fields=["order", "status"],
                name="dispense_order_status_idx",
            ),
            models.Index(
                fields=["payment_status", "created_at"],
                name="dispense_payment_idx",
            ),
        ]
        constraints = [
            models.CheckConstraint(
                condition=Q(total_amount__gte=0),
                name="ck_dispense_total_nonneg",
            ),
            models.CheckConstraint(
                condition=Q(amount_paid__gte=0),
                name="ck_dispense_paid_nonneg",
            ),
        ]

    @property
    def balance_due(self):
        total = self.total_amount or Decimal("0.00")
        paid = self.amount_paid or Decimal("0.00")
        return max(total - paid, Decimal("0.00"))

    @property
    def receipt_number(self):
        if not self.pk:
            return "Not generated"
        return f"DSP-{self.pk:08d}"

    def clean(self):
        super().clean()
        errors = {}

        total_amount = self.total_amount or Decimal("0.00")
        amount_paid = self.amount_paid or Decimal("0.00")

        if self.order_id and self.dispensed_by_id:
            if self.dispensed_by.pharmacy_id != self.order.pharmacy_id:
                errors["dispensed_by"] = (
                    "The pharmacist must belong to the order pharmacy."
                )
            elif not self.dispensed_by.is_active or self.dispensed_by.is_deleted:
                errors["dispensed_by"] = (
                    "The pharmacist assignment is inactive."
                )

        if self.order_id and self.order.status in {
            PharmacyOrder.Status.REJECTED,
            PharmacyOrder.Status.CANCELLED,
        }:
            errors["order"] = "A rejected or cancelled order cannot be dispensed."

        if amount_paid > total_amount:
            errors["amount_paid"] = (
                "The paid amount cannot exceed the total amount."
            )

        if self.payment_status == self.PaymentStatus.UNPAID:
            if amount_paid != Decimal("0.00"):
                errors["amount_paid"] = (
                    "An unpaid dispense must have a paid amount of zero."
                )

        elif self.payment_status == self.PaymentStatus.PARTIALLY_PAID:
            if not Decimal("0.00") < amount_paid < total_amount:
                errors["amount_paid"] = (
                    "A partial payment must be greater than zero "
                    "and lower than the total amount."
                )

            if not self.payment_method:
                errors["payment_method"] = (
                    "A payment method is required for partial payments."
                )

        elif self.payment_status == self.PaymentStatus.PAID:
            if amount_paid != total_amount:
                errors["amount_paid"] = (
                    "For a paid dispense, the paid amount must "
                    "equal the total amount."
                )

            if not self.payment_method:
                errors["payment_method"] = (
                    "A payment method is required for paid dispenses."
                )

        if (
            self.payment_method
            in {
                self.PaymentMethod.CARD,
                self.PaymentMethod.BANK_TRANSFER,
            }
            and not (self.transaction_reference or "").strip()
        ):
            errors["transaction_reference"] = (
                "A transaction reference is required for "
                "card and bank transfer payments."
            )

        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.received_by_name = " ".join(
            (self.received_by_name or "").split()
        ).strip()
        self.transaction_reference = (
            self.transaction_reference or ""
        ).strip()

        if self.status == self.Status.COMPLETED and not self.dispensed_at:
            self.dispensed_at = timezone.now()

        if self.payment_status == self.PaymentStatus.PAID:
            if not self.paid_at:
                self.paid_at = timezone.now()
        else:
            self.paid_at = None

        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"Dispense #{self.pk} | Order #{self.order_id}"


class DispenseItem(SoftDeleteModel):
    dispense = models.ForeignKey(
        Dispense,
        on_delete=models.PROTECT,
        related_name="items",
    )
    order_item = models.ForeignKey(
        PharmacyOrderItem,
        on_delete=models.PROTECT,
        related_name="dispense_items",
    )
    stock_batch = models.ForeignKey(
        StockBatch,
        on_delete=models.PROTECT,
        related_name="dispense_items",
    )
    quantity = models.PositiveIntegerField()
    unit_price = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.00"))],
    )
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["dispense_id", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["dispense", "order_item", "stock_batch"],
                condition=Q(is_deleted=False),
                name="uq_dispense_item_batch",
            ),
            models.CheckConstraint(
                condition=Q(quantity__gt=0),
                name="ck_dispense_item_quantity_pos",
            ),
            models.CheckConstraint(
                condition=Q(unit_price__gte=0),
                name="ck_dispense_item_price_nonneg",
            ),
        ]

    @property
    def total_price(self):
        return self.quantity * self.unit_price

    def clean(self):
        super().clean()
        errors = {}

        if self.dispense_id and self.order_item_id:
            if self.order_item.order_id != self.dispense.order_id:
                errors["order_item"] = "The order item must belong to the dispense order."

        if self.dispense_id and self.stock_batch_id:
            if self.stock_batch.inventory.pharmacy_id != self.dispense.order.pharmacy_id:
                errors["stock_batch"] = "The stock batch must belong to the order pharmacy."

        if self.order_item_id and self.stock_batch_id and self.order_item.medicine_id:
            if self.stock_batch.inventory.medicine_id != self.order_item.medicine_id:
                errors["stock_batch"] = "The stock batch medicine does not match the order item."

        if self.quantity < 1:
            errors["quantity"] = "Dispensed quantity must be greater than zero."

        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.order_item} | Quantity {self.quantity}"


class PharmacySale(SoftDeleteModel):
    """
    A direct point-of-sale transaction.

    This model is available to both standalone and hospital-integrated
    pharmacies. Prescription dispensing continues to use PharmacyOrder and
    Dispense, while walk-in sales use PharmacySale.
    """

    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        COMPLETED = "completed", "Completed"
        VOIDED = "voided", "Voided"

    class PaymentStatus(models.TextChoices):
        UNPAID = "unpaid", "Unpaid"
        PARTIALLY_PAID = "partially_paid", "Partially Paid"
        PAID = "paid", "Paid"

    class PaymentMethod(models.TextChoices):
        CASH = "cash", "Cash"
        CARD = "card", "Card"
        BANK_TRANSFER = "bank_transfer", "Bank Transfer"
        INSURANCE = "insurance", "Insurance"
        OTHER = "other", "Other"

    pharmacy = models.ForeignKey(
        Pharmacy,
        on_delete=models.PROTECT,
        related_name="direct_sales",
    )
    cashier = models.ForeignKey(
        PharmacyStaffAssignment,
        on_delete=models.PROTECT,
        related_name="direct_sales",
    )
    customer_name = models.CharField(
        max_length=200,
        blank=True,
        default="",
    )
    customer_phone = models.CharField(
        max_length=30,
        blank=True,
        default="",
    )
    status = models.CharField(
        max_length=12,
        choices=Status.choices,
        default=Status.DRAFT,
        db_index=True,
    )
    subtotal = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=Decimal("0.00"),
        validators=[MinValueValidator(Decimal("0.00"))],
    )
    discount_amount = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=Decimal("0.00"),
        validators=[MinValueValidator(Decimal("0.00"))],
    )
    total_amount = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=Decimal("0.00"),
        validators=[MinValueValidator(Decimal("0.00"))],
    )
    amount_paid = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=Decimal("0.00"),
        validators=[MinValueValidator(Decimal("0.00"))],
    )
    payment_status = models.CharField(
        max_length=20,
        choices=PaymentStatus.choices,
        default=PaymentStatus.UNPAID,
        db_index=True,
    )
    payment_method = models.CharField(
        max_length=20,
        choices=PaymentMethod.choices,
        blank=True,
        default="",
    )
    transaction_reference = models.CharField(
        max_length=100,
        blank=True,
        default="",
    )
    notes = models.TextField(blank=True, default="")
    completed_at = models.DateTimeField(
        null=True,
        blank=True,
        db_index=True,
    )
    paid_at = models.DateTimeField(null=True, blank=True)
    voided_at = models.DateTimeField(null=True, blank=True)
    voided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="pharmacy_sales_voided",
        null=True,
        blank=True,
    )
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [
            models.Index(
                fields=["pharmacy", "status", "created_at"],
                name="sale_pharm_status_date_idx",
            ),
            models.Index(
                fields=["payment_status", "created_at"],
                name="sale_payment_status_idx",
            ),
        ]
        constraints = [
            models.CheckConstraint(
                condition=Q(subtotal__gte=0),
                name="ck_sale_subtotal_nonneg",
            ),
            models.CheckConstraint(
                condition=Q(discount_amount__gte=0),
                name="ck_sale_discount_nonneg",
            ),
            models.CheckConstraint(
                condition=Q(total_amount__gte=0),
                name="ck_sale_total_nonneg",
            ),
            models.CheckConstraint(
                condition=Q(amount_paid__gte=0),
                name="ck_sale_paid_nonneg",
            ),
            models.CheckConstraint(
                condition=Q(discount_amount__lte=models.F("subtotal")),
                name="ck_sale_discount_lte_subtotal",
            ),
            models.CheckConstraint(
                condition=Q(amount_paid__lte=models.F("total_amount")),
                name="ck_sale_paid_lte_total",
            ),
        ]

    @property
    def sale_number(self):
        if not self.pk:
            return "Not generated"
        return f"POS-{self.pk:08d}"

    @property
    def balance_due(self):
        total = self.total_amount or Decimal("0.00")
        paid = self.amount_paid or Decimal("0.00")
        return max(total - paid, Decimal("0.00"))

    @property
    def total_cost(self):
        total = Decimal("0.00")
        for item in self.items.all():
            for allocation in item.allocations.all():
                total += allocation.total_cost
        return total

    @property
    def gross_profit(self):
        return (self.total_amount or Decimal("0.00")) - self.total_cost

    def clean(self):
        super().clean()
        errors = {}

        subtotal = self.subtotal or Decimal("0.00")
        discount = self.discount_amount or Decimal("0.00")
        total = self.total_amount or Decimal("0.00")
        paid = self.amount_paid or Decimal("0.00")
        expected_total = subtotal - discount

        if self.cashier_id:
            if self.cashier.pharmacy_id != self.pharmacy_id:
                errors["cashier"] = (
                    "The cashier must be assigned to the selected pharmacy."
                )
            elif self.cashier.is_deleted or not self.cashier.is_active:
                errors["cashier"] = "The cashier assignment is inactive."

        if discount > subtotal:
            errors["discount_amount"] = (
                "The discount cannot exceed the subtotal."
            )

        if total != expected_total:
            errors["total_amount"] = (
                "The total amount must equal subtotal minus discount."
            )

        if paid > total:
            errors["amount_paid"] = (
                "The paid amount cannot exceed the total amount."
            )

        if self.payment_status == self.PaymentStatus.UNPAID:
            if paid != Decimal("0.00"):
                errors["amount_paid"] = (
                    "An unpaid sale must have a paid amount of zero."
                )

        elif self.payment_status == self.PaymentStatus.PARTIALLY_PAID:
            if not Decimal("0.00") < paid < total:
                errors["amount_paid"] = (
                    "A partial payment must be greater than zero "
                    "and lower than the total amount."
                )
            if not self.payment_method:
                errors["payment_method"] = (
                    "A payment method is required for partial payments."
                )

        elif self.payment_status == self.PaymentStatus.PAID:
            if paid != total:
                errors["amount_paid"] = (
                    "For a paid sale, the paid amount must equal "
                    "the total amount."
                )
            if not self.payment_method:
                errors["payment_method"] = (
                    "A payment method is required for paid sales."
                )

        if (
            self.payment_method
            in {
                self.PaymentMethod.CARD,
                self.PaymentMethod.BANK_TRANSFER,
            }
            and not (self.transaction_reference or "").strip()
        ):
            errors["transaction_reference"] = (
                "A transaction reference is required for card "
                "and bank transfer payments."
            )

        if self.status == self.Status.VOIDED and not self.voided_by_id:
            errors["voided_by"] = (
                "The user who voided the sale is required."
            )

        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.customer_name = " ".join(
            (self.customer_name or "").split()
        ).strip()
        self.customer_phone = (
            self.customer_phone or ""
        ).strip()
        self.transaction_reference = (
            self.transaction_reference or ""
        ).strip()

        now = timezone.now()
        if self.status == self.Status.COMPLETED and not self.completed_at:
            self.completed_at = now
        if self.status == self.Status.VOIDED and not self.voided_at:
            self.voided_at = now

        if self.payment_status == self.PaymentStatus.PAID:
            if not self.paid_at:
                self.paid_at = now
        else:
            self.paid_at = None

        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.sale_number} | {self.pharmacy}"


class PharmacySaleItem(SoftDeleteModel):
    sale = models.ForeignKey(
        PharmacySale,
        on_delete=models.PROTECT,
        related_name="items",
    )
    medicine = models.ForeignKey(
        Medicine,
        on_delete=models.PROTECT,
        related_name="direct_sale_items",
    )
    quantity = models.PositiveIntegerField()
    unit_price = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.00"))],
    )
    discount_amount = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=Decimal("0.00"),
        validators=[MinValueValidator(Decimal("0.00"))],
    )
    notes = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["sale_id", "id"]
        indexes = [
            models.Index(
                fields=["sale", "medicine"],
                name="sale_item_medicine_idx",
            ),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["sale", "medicine"],
                condition=Q(is_deleted=False),
                name="uq_sale_medicine",
            ),
            models.CheckConstraint(
                condition=Q(quantity__gt=0),
                name="ck_sale_item_quantity_pos",
            ),
            models.CheckConstraint(
                condition=Q(unit_price__gte=0),
                name="ck_sale_item_price_nonneg",
            ),
            models.CheckConstraint(
                condition=Q(discount_amount__gte=0),
                name="ck_sale_item_discount_nonneg",
            ),
        ]

    @property
    def gross_amount(self):
        return self.quantity * self.unit_price

    @property
    def total_price(self):
        return max(
            self.gross_amount - self.discount_amount,
            Decimal("0.00"),
        )

    @property
    def allocated_quantity(self):
        result = self.allocations.aggregate(
            total=Coalesce(Sum("quantity"), 0),
        )
        return int(result["total"] or 0)

    def clean(self):
        super().clean()
        errors = {}

        if self.sale_id and self.medicine_id:
            pharmacy_hospital_id = self.sale.pharmacy.branch.hospital_id
            if self.medicine.hospital_id != pharmacy_hospital_id:
                errors["medicine"] = (
                    "The medicine and pharmacy must belong to "
                    "the same organization."
                )

        if self.quantity < 1:
            errors["quantity"] = (
                "Sale quantity must be greater than zero."
            )

        if self.discount_amount > self.gross_amount:
            errors["discount_amount"] = (
                "The item discount cannot exceed its gross amount."
            )

        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self):
        return (
            f"{self.medicine} | {self.quantity} | "
            f"{self.sale.sale_number}"
        )


class PharmacySaleAllocation(SoftDeleteModel):
    """
    Connects a POS sale item to one or more stock batches.

    Services allocate stock using FEFO (earliest expiry first), allowing one
    sale line to consume quantities from multiple batches while preserving a
    complete audit trail and purchase-cost snapshot.
    """

    sale_item = models.ForeignKey(
        PharmacySaleItem,
        on_delete=models.PROTECT,
        related_name="allocations",
    )
    stock_batch = models.ForeignKey(
        StockBatch,
        on_delete=models.PROTECT,
        related_name="direct_sale_allocations",
    )
    quantity = models.PositiveIntegerField()
    unit_purchase_price = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=Decimal("0.00"),
        validators=[MinValueValidator(Decimal("0.00"))],
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["sale_item_id", "stock_batch__expiry_date", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["sale_item", "stock_batch"],
                condition=Q(is_deleted=False),
                name="uq_sale_item_batch",
            ),
            models.CheckConstraint(
                condition=Q(quantity__gt=0),
                name="ck_sale_alloc_quantity_pos",
            ),
            models.CheckConstraint(
                condition=Q(unit_purchase_price__gte=0),
                name="ck_sale_alloc_cost_nonneg",
            ),
        ]

    @property
    def total_cost(self):
        return self.quantity * self.unit_purchase_price

    def clean(self):
        super().clean()
        errors = {}

        if self.sale_item_id and self.stock_batch_id:
            sale_pharmacy_id = self.sale_item.sale.pharmacy_id
            batch_pharmacy_id = self.stock_batch.inventory.pharmacy_id
            if batch_pharmacy_id != sale_pharmacy_id:
                errors["stock_batch"] = (
                    "The stock batch must belong to the sale pharmacy."
                )
            elif (
                self.stock_batch.inventory.medicine_id
                != self.sale_item.medicine_id
            ):
                errors["stock_batch"] = (
                    "The stock batch medicine does not match "
                    "the sale item."
                )

        if self.quantity < 1:
            errors["quantity"] = (
                "Allocated quantity must be greater than zero."
            )

        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self):
        return (
            f"{self.sale_item} | Batch {self.stock_batch_id} | "
            f"Quantity {self.quantity}"
        )


class StockMovement(models.Model):
    class Types(models.TextChoices):
        RECEIPT = "receipt", "Receipt"
        DISPENSE = "dispense", "Dispense"
        DIRECT_SALE = "direct_sale", "Direct Sale"
        PATIENT_RETURN = "patient_return", "Patient Return"
        SUPPLIER_RETURN = "supplier_return", "Supplier Return"
        ADJUSTMENT_IN = "adjustment_in", "Adjustment In"
        ADJUSTMENT_OUT = "adjustment_out", "Adjustment Out"
        EXPIRED = "expired", "Expired"
        DAMAGED = "damaged", "Damaged"

    stock_batch = models.ForeignKey(
        StockBatch,
        on_delete=models.PROTECT,
        related_name="movements",
    )
    movement_type = models.CharField(
        max_length=20,
        choices=Types.choices,
        db_index=True,
    )
    quantity = models.PositiveIntegerField()
    balance_before = models.PositiveIntegerField()
    balance_after = models.PositiveIntegerField()
    dispense_item = models.ForeignKey(
        DispenseItem,
        on_delete=models.PROTECT,
        related_name="stock_movements",
        null=True,
        blank=True,
    )
    direct_sale_allocation = models.ForeignKey(
        PharmacySaleAllocation,
        on_delete=models.PROTECT,
        related_name="stock_movements",
        null=True,
        blank=True,
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="pharmacy_stock_movements",
    )
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [
            models.Index(
                fields=["stock_batch", "created_at"],
                name="stock_move_batch_date_idx",
            ),
            models.Index(
                fields=["movement_type", "created_at"],
                name="stock_move_type_date_idx",
            ),
        ]
        constraints = [
            models.CheckConstraint(
                condition=Q(quantity__gt=0),
                name="ck_stock_move_quantity_pos",
            ),
        ]

    def clean(self):
        super().clean()
        errors = {}

        if self.quantity < 1:
            errors["quantity"] = (
                "Movement quantity must be greater than zero."
            )

        if self.dispense_item_id and self.direct_sale_allocation_id:
            errors["direct_sale_allocation"] = (
                "A stock movement cannot reference both a prescription "
                "dispense and a direct sale."
            )

        if (
            self.dispense_item_id
            and self.movement_type != self.Types.DISPENSE
        ):
            errors["dispense_item"] = (
                "A dispense item can only be linked to a dispense movement."
            )

        if (
            self.direct_sale_allocation_id
            and self.movement_type
            not in {
                self.Types.DIRECT_SALE,
                self.Types.PATIENT_RETURN,
            }
        ):
            errors["direct_sale_allocation"] = (
                "A direct sale allocation can only be linked to its "
                "sale movement or its return movement."
            )

        if (
            self.movement_type == self.Types.DIRECT_SALE
            and not self.direct_sale_allocation_id
        ):
            errors["direct_sale_allocation"] = (
                "A direct-sale movement requires a sale allocation."
            )

        if self.dispense_item_id:
            if self.dispense_item.stock_batch_id != self.stock_batch_id:
                errors["stock_batch"] = (
                    "The movement batch must match the dispense item batch."
                )

        if self.direct_sale_allocation_id:
            if (
                self.direct_sale_allocation.stock_batch_id
                != self.stock_batch_id
            ):
                errors["stock_batch"] = (
                    "The movement batch must match the direct sale "
                    "allocation batch."
                )

        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        if self.pk:
            raise ValidationError("Stock movements are immutable and cannot be edited.")
        self.full_clean()
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Stock movements are immutable and cannot be deleted.")

    def __str__(self):
        return f"{self.get_movement_type_display()} | {self.quantity} | Batch {self.stock_batch_id}"
