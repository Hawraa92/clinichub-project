from django.contrib import admin

from .models import (
    Dispense,
    DispenseItem,
    Medicine,
    Pharmacy,
    PharmacyInventory,
    PharmacyOrder,
    PharmacyOrderItem,
    PharmacyStaffAssignment,
    StockBatch,
    StockMovement,
)


class SoftDeleteAdmin(admin.ModelAdmin):
    readonly_fields = (
        "created_at",
        "updated_at",
        "deleted_at",
        "deleted_by",
    )


@admin.register(Pharmacy)
class PharmacyAdmin(SoftDeleteAdmin):
    list_display = (
        "name",
        "code",
        "branch",
        "hospital_name",
        "pharmacy_type",
        "is_active",
        "updated_at",
    )
    list_filter = (
        "pharmacy_type",
        "is_active",
        "branch__hospital",
        "branch",
        "is_deleted",
    )
    search_fields = (
        "name",
        "code",
        "license_number",
        "branch__name",
        "branch__hospital__name",
    )
    list_select_related = (
        "branch",
        "branch__hospital",
    )
    ordering = (
        "branch__hospital__name",
        "branch__name",
        "name",
    )

    @admin.display(
        description="Hospital",
        ordering="branch__hospital__name",
    )
    def hospital_name(self, obj):
        return obj.branch.hospital.name


@admin.register(PharmacyStaffAssignment)
class PharmacyStaffAssignmentAdmin(SoftDeleteAdmin):
    list_display = (
        "staff_name",
        "staff_email",
        "pharmacy",
        "is_manager",
        "is_active",
        "start_date",
        "end_date",
    )
    list_filter = (
        "is_manager",
        "is_active",
        "pharmacy",
        "pharmacy__branch",
        "pharmacy__branch__hospital",
        "is_deleted",
    )
    search_fields = (
        "staff_assignment__user__email",
        "staff_assignment__user__first_name",
        "staff_assignment__user__last_name",
        "pharmacy__name",
        "pharmacy__code",
    )
    raw_id_fields = (
        "pharmacy",
        "staff_assignment",
    )
    list_select_related = (
        "pharmacy",
        "pharmacy__branch",
        "staff_assignment",
        "staff_assignment__user",
    )

    @admin.display(
        description="Staff",
        ordering="staff_assignment__user__first_name",
    )
    def staff_name(self, obj):
        return str(obj.staff_assignment.user)

    @admin.display(
        description="Email",
        ordering="staff_assignment__user__email",
    )
    def staff_email(self, obj):
        return obj.staff_assignment.user.email


@admin.register(Medicine)
class MedicineAdmin(SoftDeleteAdmin):
    list_display = (
        "code",
        "medicine_name",
        "strength",
        "dosage_form",
        "hospital",
        "requires_prescription",
        "is_controlled",
        "is_active",
    )
    list_filter = (
        "hospital",
        "dosage_form",
        "requires_prescription",
        "is_controlled",
        "is_active",
        "is_deleted",
    )
    search_fields = (
        "code",
        "barcode",
        "generic_name",
        "brand_name",
        "manufacturer",
    )
    raw_id_fields = ("hospital",)
    list_select_related = ("hospital",)
    ordering = (
        "generic_name",
        "brand_name",
        "strength",
    )

    @admin.display(
        description="Medicine",
        ordering="generic_name",
    )
    def medicine_name(self, obj):
        return obj.display_name


@admin.register(PharmacyInventory)
class PharmacyInventoryAdmin(SoftDeleteAdmin):
    list_display = (
        "pharmacy",
        "medicine",
        "quantity_available",
        "reorder_level",
        "target_stock",
        "reorder_required",
        "is_active",
    )
    list_filter = (
        "is_active",
        "pharmacy",
        "pharmacy__branch",
        "pharmacy__branch__hospital",
        "is_deleted",
    )
    search_fields = (
        "pharmacy__name",
        "pharmacy__code",
        "medicine__code",
        "medicine__generic_name",
        "medicine__brand_name",
        "medicine__barcode",
    )
    raw_id_fields = (
        "pharmacy",
        "medicine",
    )
    list_select_related = (
        "pharmacy",
        "medicine",
    )

    @admin.display(description="Available Quantity")
    def quantity_available(self, obj):
        return obj.quantity_on_hand

    @admin.display(
        description="Needs Reorder",
        boolean=True,
    )
    def reorder_required(self, obj):
        return obj.needs_reorder


@admin.register(StockBatch)
class StockBatchAdmin(SoftDeleteAdmin):
    list_display = (
        "batch_number",
        "medicine_name",
        "pharmacy_name",
        "expiry_date",
        "received_quantity",
        "quantity_on_hand",
        "purchase_price",
        "selling_price",
        "expired",
        "is_active",
    )
    list_filter = (
        "is_active",
        "expiry_date",
        "inventory__pharmacy",
        "inventory__pharmacy__branch",
        "inventory__pharmacy__branch__hospital",
        "is_deleted",
    )
    search_fields = (
        "batch_number",
        "supplier_name",
        "inventory__medicine__code",
        "inventory__medicine__generic_name",
        "inventory__medicine__brand_name",
        "inventory__pharmacy__name",
    )
    raw_id_fields = ("inventory",)
    list_select_related = (
        "inventory",
        "inventory__medicine",
        "inventory__pharmacy",
    )
    date_hierarchy = "received_at"
    ordering = (
        "expiry_date",
        "received_at",
    )

    @admin.display(
        description="Medicine",
        ordering="inventory__medicine__generic_name",
    )
    def medicine_name(self, obj):
        return obj.inventory.medicine.display_name

    @admin.display(
        description="Pharmacy",
        ordering="inventory__pharmacy__name",
    )
    def pharmacy_name(self, obj):
        return obj.inventory.pharmacy.name

    @admin.display(
        description="Expired",
        boolean=True,
    )
    def expired(self, obj):
        return obj.is_expired


@admin.register(PharmacyOrder)
class PharmacyOrderAdmin(SoftDeleteAdmin):
    list_display = (
        "id",
        "prescription_number",
        "pharmacy",
        "priority",
        "status",
        "sent_by",
        "assigned_to",
        "sent_at",
        "completed_at",
    )
    list_filter = (
        "status",
        "priority",
        "pharmacy",
        "pharmacy__branch",
        "pharmacy__branch__hospital",
        "sent_at",
        "is_deleted",
    )
    search_fields = (
        "=id",
        "=prescription__id",
        "pharmacy__name",
        "sent_by__email",
        "assigned_to__staff_assignment__user__email",
    )
    raw_id_fields = (
        "prescription",
        "pharmacy",
        "sent_by",
        "assigned_to",
    )
    list_select_related = (
        "prescription",
        "pharmacy",
        "sent_by",
        "assigned_to",
    )
    readonly_fields = SoftDeleteAdmin.readonly_fields + (
        "sent_at",
        "accepted_at",
        "completed_at",
    )
    date_hierarchy = "sent_at"

    @admin.display(
        description="Prescription",
        ordering="prescription_id",
    )
    def prescription_number(self, obj):
        return f"#{obj.prescription_id}"


@admin.register(PharmacyOrderItem)
class PharmacyOrderItemAdmin(SoftDeleteAdmin):
    list_display = (
        "id",
        "order_number",
        "medication_name",
        "medicine",
        "requested_quantity",
        "requested_unit",
        "dispensed_quantity_value",
        "remaining_quantity_value",
        "status",
        "is_substitution",
    )
    list_filter = (
        "status",
        "is_substitution",
        "order__pharmacy",
        "order__pharmacy__branch__hospital",
        "is_deleted",
    )
    search_fields = (
        "=order__id",
        "medication_name",
        "dosage",
        "medicine__code",
        "medicine__generic_name",
        "medicine__brand_name",
    )
    raw_id_fields = (
        "order",
        "prescription_medication",
        "medicine",
    )
    list_select_related = (
        "order",
        "medicine",
        "prescription_medication",
    )

    @admin.display(
        description="Order",
        ordering="order_id",
    )
    def order_number(self, obj):
        return f"#{obj.order_id}"

    @admin.display(description="Dispensed")
    def dispensed_quantity_value(self, obj):
        return obj.dispensed_quantity

    @admin.display(description="Remaining")
    def remaining_quantity_value(self, obj):
        return obj.remaining_quantity


@admin.register(Dispense)
class DispenseAdmin(SoftDeleteAdmin):
    list_display = (
        "id",
        "order_number",
        "pharmacy_name",
        "dispensed_by",
        "status",
        "total_amount",
        "dispensed_at",
        "created_at",
    )
    list_filter = (
        "status",
        "order__pharmacy",
        "order__pharmacy__branch",
        "order__pharmacy__branch__hospital",
        "dispensed_at",
        "is_deleted",
    )
    search_fields = (
        "=id",
        "=order__id",
        "dispensed_by__staff_assignment__user__email",
        "order__pharmacy__name",
    )
    raw_id_fields = (
        "order",
        "dispensed_by",
    )
    list_select_related = (
        "order",
        "order__pharmacy",
        "dispensed_by",
    )
    readonly_fields = SoftDeleteAdmin.readonly_fields + (
        "dispensed_at",
    )
    date_hierarchy = "created_at"

    @admin.display(
        description="Order",
        ordering="order_id",
    )
    def order_number(self, obj):
        return f"#{obj.order_id}"

    @admin.display(
        description="Pharmacy",
        ordering="order__pharmacy__name",
    )
    def pharmacy_name(self, obj):
        return obj.order.pharmacy.name


@admin.register(DispenseItem)
class DispenseItemAdmin(SoftDeleteAdmin):
    list_display = (
        "id",
        "dispense_number",
        "order_item",
        "stock_batch",
        "quantity",
        "unit_price",
        "total_price_value",
    )
    list_filter = (
        "dispense__status",
        "dispense__order__pharmacy",
        "dispense__order__pharmacy__branch__hospital",
        "is_deleted",
    )
    search_fields = (
        "=dispense__id",
        "order_item__medication_name",
        "stock_batch__batch_number",
        "stock_batch__inventory__medicine__generic_name",
    )
    raw_id_fields = (
        "dispense",
        "order_item",
        "stock_batch",
    )
    list_select_related = (
        "dispense",
        "order_item",
        "stock_batch",
        "stock_batch__inventory",
        "stock_batch__inventory__medicine",
    )

    @admin.display(
        description="Dispense",
        ordering="dispense_id",
    )
    def dispense_number(self, obj):
        return f"#{obj.dispense_id}"

    @admin.display(description="Total Price")
    def total_price_value(self, obj):
        return obj.total_price


@admin.register(StockMovement)
class StockMovementAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "stock_batch",
        "movement_type",
        "quantity",
        "balance_before",
        "balance_after",
        "created_by",
        "created_at",
    )
    list_filter = (
        "movement_type",
        "stock_batch__inventory__pharmacy",
        "stock_batch__inventory__pharmacy__branch__hospital",
        "created_at",
    )
    search_fields = (
        "=id",
        "stock_batch__batch_number",
        "stock_batch__inventory__medicine__generic_name",
        "stock_batch__inventory__medicine__brand_name",
        "created_by__email",
    )
    raw_id_fields = (
        "stock_batch",
        "dispense_item",
        "created_by",
    )
    list_select_related = (
        "stock_batch",
        "created_by",
        "dispense_item",
    )
    readonly_fields = (
        "stock_batch",
        "movement_type",
        "quantity",
        "balance_before",
        "balance_after",
        "dispense_item",
        "created_by",
        "notes",
        "created_at",
    )
    date_hierarchy = "created_at"

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False