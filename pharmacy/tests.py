import shutil
import tempfile
from datetime import date, timedelta
from decimal import Decimal

from appointments.models import Appointment, Notification
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase, override_settings
from django.utils import timezone
from doctor.models import Doctor
from hospital.models import Branch, Hospital, StaffAssignment
from patient.models import Patient
from prescription.models import Medication, Prescription

from pharmacy.models import (
    Dispense,
    Medicine,
    Pharmacy,
    PharmacyInventory,
    PharmacyOrder,
    PharmacyOrderItem,
    PharmacyStaffAssignment,
    StockBatch,
    StockMovement,
)
from pharmacy.services import (
    accept_pharmacy_order,
    complete_order_dispense,
    reject_pharmacy_order,
    send_prescription_to_pharmacy,
    start_pharmacy_order,
    void_completed_dispense,
)

User = get_user_model()


class PharmacyModelsTests(TestCase):
    def setUp(self):
        self.hospital = Hospital.objects.create(
            name="Al-Hayat Hospital",
            code="HAYAT",
            is_active=True,
        )

        self.branch = Branch.objects.create(
            hospital=self.hospital,
            name="Main Branch",
            code="MAIN",
            is_active=True,
        )

        self.pharmacy = Pharmacy.objects.create(
            branch=self.branch,
            name=" Main Pharmacy ",
            code=" main-ph ",
            pharmacy_type=Pharmacy.Types.CENTRAL,
            is_active=True,
        )

        self.medicine = Medicine.objects.create(
            hospital=self.hospital,
            code=" med-001 ",
            barcode="123456789",
            generic_name=" paracetamol ",
            brand_name=" panadol ",
            strength=" 500 mg ",
            dosage_form=Medicine.DosageForms.TABLET,
            dispensing_unit=" Tablet ",
            manufacturer="Test Manufacturer",
            requires_prescription=True,
            is_active=True,
        )

        self.inventory = PharmacyInventory.objects.create(
            pharmacy=self.pharmacy,
            medicine=self.medicine,
            reorder_level=10,
            target_stock=100,
            is_active=True,
        )

        self.pharmacist_user = User.objects.create_user(
            email="pharmacist@example.com",
            password="testpass123",
            role="pharmacist",
            is_approved=True,
        )

        self.staff_assignment = StaffAssignment.objects.create(
            user=self.pharmacist_user,
            hospital=self.hospital,
            branch=self.branch,
            role=StaffAssignment.Roles.PHARMACIST,
            is_primary=True,
            is_active=True,
        )

    def test_pharmacy_normalizes_name_and_code(self):
        self.assertEqual(self.pharmacy.name, "Main Pharmacy")
        self.assertEqual(self.pharmacy.code, "MAIN-PH")
        self.assertEqual(self.pharmacy.hospital, self.hospital)
        self.assertTrue(self.pharmacy.is_active)

    def test_duplicate_pharmacy_code_is_rejected(self):
        with self.assertRaises(ValidationError):
            Pharmacy.objects.create(
                branch=self.branch,
                name="Second Pharmacy",
                code="main-ph",
                pharmacy_type=Pharmacy.Types.OUTPATIENT,
            )

    def test_medicine_normalizes_fields(self):
        self.assertEqual(self.medicine.code, "MED-001")
        self.assertEqual(self.medicine.generic_name, "paracetamol")
        self.assertEqual(self.medicine.brand_name, "panadol")
        self.assertEqual(self.medicine.strength, "500 mg")
        self.assertEqual(self.medicine.dispensing_unit, "tablet")
        self.assertEqual(
            self.medicine.display_name,
            "panadol 500 mg Tablet",
        )

    def test_duplicate_medicine_barcode_is_rejected(self):
        with self.assertRaises(ValidationError):
            Medicine.objects.create(
                hospital=self.hospital,
                code="MED-002",
                barcode="123456789",
                generic_name="Ibuprofen",
                brand_name="Brufen",
                strength="400 mg",
                dispensing_unit="tablet",
            )

    def test_inventory_calculates_available_quantity(self):
        StockBatch.objects.create(
            inventory=self.inventory,
            batch_number="BATCH-001",
            expiry_date=timezone.localdate() + timedelta(days=365),
            received_quantity=40,
            purchase_price="1000.00",
            selling_price="1500.00",
        )

        StockBatch.objects.create(
            inventory=self.inventory,
            batch_number="BATCH-EXPIRED",
            expiry_date=timezone.localdate() - timedelta(days=1),
            received_quantity=30,
            purchase_price="1000.00",
            selling_price="1500.00",
        )

        self.assertEqual(self.inventory.quantity_on_hand, 40)

    def test_inventory_reorder_status(self):
        self.assertEqual(self.inventory.quantity_on_hand, 0)
        self.assertTrue(self.inventory.needs_reorder)

        StockBatch.objects.create(
            inventory=self.inventory,
            batch_number="BATCH-REORDER",
            expiry_date=timezone.localdate() + timedelta(days=365),
            received_quantity=20,
            purchase_price="1000.00",
            selling_price="1500.00",
        )

        self.assertEqual(self.inventory.quantity_on_hand, 20)
        self.assertFalse(self.inventory.needs_reorder)

    def test_inventory_rejects_different_hospital_medicine(self):
        second_hospital = Hospital.objects.create(
            name="Second Hospital",
            code="SECOND",
        )

        foreign_medicine = Medicine.objects.create(
            hospital=second_hospital,
            code="FOREIGN-001",
            generic_name="Foreign Medicine",
            dispensing_unit="unit",
        )

        with self.assertRaises(ValidationError):
            PharmacyInventory.objects.create(
                pharmacy=self.pharmacy,
                medicine=foreign_medicine,
                reorder_level=5,
                target_stock=20,
            )

    def test_inventory_rejects_target_below_reorder_level(self):
        second_medicine = Medicine.objects.create(
            hospital=self.hospital,
            code="MED-SECOND",
            generic_name="Second Medicine",
            dispensing_unit="unit",
        )

        with self.assertRaises(ValidationError) as error:
            PharmacyInventory.objects.create(
                pharmacy=self.pharmacy,
                medicine=second_medicine,
                reorder_level=20,
                target_stock=10,
            )

        self.assertIn("target_stock", error.exception.message_dict)

    def test_stock_batch_uses_received_quantity_as_initial_stock(self):
        batch = StockBatch.objects.create(
            inventory=self.inventory,
            batch_number=" batch-001 ",
            expiry_date=timezone.localdate() + timedelta(days=365),
            received_quantity=50,
            purchase_price="1000.00",
            selling_price="1500.00",
        )

        self.assertEqual(batch.batch_number, "BATCH-001")
        self.assertEqual(batch.quantity_on_hand, 50)
        self.assertFalse(batch.is_expired)
        self.assertTrue(batch.is_available)

    def test_expired_batch_is_not_available(self):
        batch = StockBatch.objects.create(
            inventory=self.inventory,
            batch_number="EXPIRED-001",
            expiry_date=timezone.localdate() - timedelta(days=1),
            received_quantity=25,
            purchase_price="1000.00",
            selling_price="1500.00",
        )

        self.assertTrue(batch.is_expired)
        self.assertFalse(batch.is_available)
        self.assertEqual(self.inventory.quantity_on_hand, 0)

    def test_stock_batch_soft_delete_and_restore(self):
        batch = StockBatch.objects.create(
            inventory=self.inventory,
            batch_number="DELETE-001",
            expiry_date=timezone.localdate() + timedelta(days=365),
            received_quantity=15,
            purchase_price="1000.00",
            selling_price="1500.00",
        )

        batch.delete(user=self.pharmacist_user)

        self.assertFalse(
            StockBatch.objects.filter(pk=batch.pk).exists()
        )
        self.assertTrue(
            StockBatch.deleted_objects.filter(pk=batch.pk).exists()
        )

        batch.restore()

        self.assertTrue(
            StockBatch.objects.filter(pk=batch.pk).exists()
        )

    def test_valid_pharmacist_assignment(self):
        assignment = PharmacyStaffAssignment.objects.create(
            pharmacy=self.pharmacy,
            staff_assignment=self.staff_assignment,
            is_manager=True,
            is_active=True,
        )

        self.assertEqual(assignment.user, self.pharmacist_user)
        self.assertEqual(assignment.pharmacy, self.pharmacy)
        self.assertTrue(assignment.is_manager)

    def test_non_pharmacist_assignment_is_rejected(self):
        doctor_user = User.objects.create_user(
            email="doctor-pharmacy-test@example.com",
            password="testpass123",
            role="doctor",
            is_approved=True,
        )

        doctor_assignment = StaffAssignment.objects.create(
            user=doctor_user,
            hospital=self.hospital,
            branch=self.branch,
            role=StaffAssignment.Roles.DOCTOR,
            is_active=True,
        )

        with self.assertRaises(ValidationError):
            PharmacyStaffAssignment.objects.create(
                pharmacy=self.pharmacy,
                staff_assignment=doctor_assignment,
                is_active=True,
            )

    def test_stock_movement_is_immutable(self):
        batch = StockBatch.objects.create(
            inventory=self.inventory,
            batch_number="MOVEMENT-001",
            expiry_date=timezone.localdate() + timedelta(days=365),
            received_quantity=50,
            purchase_price="1000.00",
            selling_price="1500.00",
        )

        movement = StockMovement.objects.create(
            stock_batch=batch,
            movement_type=StockMovement.Types.ADJUSTMENT_OUT,
            quantity=5,
            balance_before=50,
            balance_after=45,
            created_by=self.pharmacist_user,
            notes="Inventory adjustment test",
        )

        movement.notes = "Modified note"

        with self.assertRaises(ValidationError):
            movement.save()

        with self.assertRaises(ValidationError):
            movement.delete()


class PharmacyWorkflowTests(TestCase):
    def setUp(self):
        self.media_root = tempfile.mkdtemp()
        self.media_override = override_settings(MEDIA_ROOT=self.media_root)
        self.media_override.enable()

        self.hospital = Hospital.objects.create(
            name="Workflow Hospital",
            code="WORKFLOW-HOSP",
            is_active=True,
        )

        self.branch = Branch.objects.create(
            hospital=self.hospital,
            name="Workflow Branch",
            code="WORKFLOW-BR",
            is_active=True,
        )

        self.doctor_user = User.objects.create_user(
            email="workflow-doctor@example.com",
            password="testpass123",
            role="doctor",
            is_approved=True,
        )

        self.doctor = Doctor.objects.create(
            user=self.doctor_user,
            specialty="General Medicine",
        )

        self.doctor_staff_assignment = StaffAssignment.objects.create(
            user=self.doctor_user,
            hospital=self.hospital,
            branch=self.branch,
            role=StaffAssignment.Roles.DOCTOR,
            is_primary=True,
            is_active=True,
        )

        self.patient_user = User.objects.create_user(
            email="workflow-patient@example.com",
            password="testpass123",
            role="patient",
            is_approved=True,
        )

        self.patient, patient_created = Patient.objects.get_or_create(
            user=self.patient_user,
            defaults={
                "full_name": "Workflow Patient",
                "date_of_birth": date(1990, 1, 1),
            },
        )

        if not patient_created:
            self.patient.full_name = "Workflow Patient"
            self.patient.date_of_birth = date(1990, 1, 1)
            self.patient.save()

        self.appointment = Appointment.objects.create(
            doctor=self.doctor,
            patient=self.patient,
            branch=self.branch,
            scheduled_time=timezone.now() + timedelta(days=1),
        )

        self.prescription = Prescription.objects.create(
            appointment=self.appointment,
            patient=self.patient,
            doctor=self.doctor,
            patient_full_name=self.patient.full_name,
            age=36,
            diagnosis="Test diagnosis",
        )

        self.prescription_medication = Medication.objects.create(
            prescription=self.prescription,
            name="Panadol",
            dosage="500 mg twice daily",
        )

        self.pharmacy = Pharmacy.objects.create(
            branch=self.branch,
            name="Workflow Pharmacy",
            code="WORKFLOW-PH",
            pharmacy_type=Pharmacy.Types.CENTRAL,
            is_active=True,
        )

        self.medicine = Medicine.objects.create(
            hospital=self.hospital,
            code="PANADOL-500",
            barcode="987654321",
            generic_name="Paracetamol",
            brand_name="Panadol",
            strength="500 mg",
            dosage_form=Medicine.DosageForms.TABLET,
            dispensing_unit="tablet",
            requires_prescription=True,
            is_active=True,
        )

        self.inventory = PharmacyInventory.objects.create(
            pharmacy=self.pharmacy,
            medicine=self.medicine,
            reorder_level=2,
            target_stock=20,
            is_active=True,
        )

        self.stock_batch = StockBatch.objects.create(
            inventory=self.inventory,
            batch_number="WORKFLOW-BATCH",
            expiry_date=timezone.localdate() + timedelta(days=365),
            received_quantity=10,
            purchase_price=Decimal("1000.00"),
            selling_price=Decimal("1500.00"),
            supplier_name="Workflow Supplier",
            is_active=True,
        )

        self.pharmacist_user = User.objects.create_user(
            email="workflow-pharmacist@example.com",
            password="testpass123",
            role="pharmacist",
            is_approved=True,
        )

        self.hospital_staff_assignment = StaffAssignment.objects.create(
            user=self.pharmacist_user,
            hospital=self.hospital,
            branch=self.branch,
            role=StaffAssignment.Roles.PHARMACIST,
            is_primary=True,
            is_active=True,
        )

        self.pharmacist_assignment = PharmacyStaffAssignment.objects.create(
            pharmacy=self.pharmacy,
            staff_assignment=self.hospital_staff_assignment,
            is_manager=True,
            is_active=True,
        )

    def tearDown(self):
        self.media_override.disable()
        shutil.rmtree(self.media_root, ignore_errors=True)
        super().tearDown()

    def _send_order(self):
        return send_prescription_to_pharmacy(
            prescription=self.prescription,
            pharmacy=self.pharmacy,
            sent_by=self.doctor_user,
            priority=PharmacyOrder.Priority.NORMAL,
            doctor_notes="Please dispense as prescribed.",
        )

    def _accepted_order(self):
        order = self._send_order()
        return accept_pharmacy_order(
            order=order,
            pharmacist_assignment=self.pharmacist_assignment,
        )

    def test_doctor_can_send_prescription_to_pharmacy(self):
        order = self._send_order()
        self.prescription.refresh_from_db()

        self.assertEqual(order.status, PharmacyOrder.Status.SENT)
        self.assertEqual(self.prescription.status, "sent")
        self.assertEqual(order.items.count(), 1)

        item = order.items.get()

        self.assertEqual(
            item.prescription_medication,
            self.prescription_medication,
        )
        self.assertEqual(item.medicine, self.medicine)
        self.assertEqual(item.medication_name, "Panadol")
        self.assertEqual(item.requested_quantity, 1)
        self.assertEqual(item.requested_unit, "tablet")

    def test_completed_prescription_can_be_sent_to_pharmacy(self):
        self.prescription.status = "completed"
        self.prescription.save(update_fields=["status"])

        order = self._send_order()

        self.assertEqual(order.status, PharmacyOrder.Status.SENT)
        self.assertEqual(order.prescription, self.prescription)
        self.assertEqual(order.pharmacy, self.pharmacy)
        self.assertEqual(order.items.count(), 1)

    def test_canceled_prescription_cannot_be_sent_to_pharmacy(self):
        self.prescription.status = "canceled"
        self.prescription.save(update_fields=["status"])

        with self.assertRaisesMessage(
            ValidationError,
            "A canceled prescription cannot be sent.",
        ):
            self._send_order()

        self.assertFalse(
            PharmacyOrder.objects.filter(
                prescription=self.prescription,
            ).exists()
        )

        self.prescription.refresh_from_db()
        self.assertEqual(self.prescription.status, "canceled")

    def test_unauthorized_user_cannot_send_prescription(self):
        with self.assertRaises(ValidationError):
            send_prescription_to_pharmacy(
                prescription=self.prescription,
                pharmacy=self.pharmacy,
                sent_by=self.patient_user,
            )

        self.assertEqual(PharmacyOrder.objects.count(), 0)

        self.prescription.refresh_from_db()
        self.assertEqual(self.prescription.status, "draft")

    def test_duplicate_active_order_is_rejected(self):
        first_order = self._send_order()

        with self.assertRaises(ValidationError):
            self._send_order()

        self.assertEqual(
            PharmacyOrder.objects.filter(
                prescription=self.prescription,
            ).count(),
            1,
        )
        self.assertTrue(
            PharmacyOrder.objects.filter(pk=first_order.pk).exists()
        )

    def test_pharmacist_can_accept_and_start_order(self):
        order = self._send_order()

        order = accept_pharmacy_order(
            order=order,
            pharmacist_assignment=self.pharmacist_assignment,
        )

        self.assertEqual(order.status, PharmacyOrder.Status.ACCEPTED)
        self.assertEqual(order.assigned_to, self.pharmacist_assignment)
        self.assertIsNotNone(order.accepted_at)

        order = start_pharmacy_order(
            order=order,
            pharmacist_assignment=self.pharmacist_assignment,
        )

        self.assertEqual(order.status, PharmacyOrder.Status.IN_PROGRESS)

    def test_reject_order_returns_prescription_to_draft(self):
        order = self._accepted_order()

        order = reject_pharmacy_order(
            order=order,
            pharmacist_assignment=self.pharmacist_assignment,
            reason="Medicine is unavailable.",
        )

        self.prescription.refresh_from_db()

        self.assertEqual(order.status, PharmacyOrder.Status.REJECTED)
        self.assertEqual(
            order.rejection_reason,
            "Medicine is unavailable.",
        )
        self.assertEqual(self.prescription.status, "draft")

    def test_complete_dispense_reduces_stock(self):
        order = self._accepted_order()
        order_item = order.items.get()

        dispense = complete_order_dispense(
            order=order,
            pharmacist_assignment=self.pharmacist_assignment,
            allocations=[
                {
                    "order_item": order_item,
                    "stock_batch": self.stock_batch,
                    "quantity": 1,
                }
            ],
            notes="Dispensed successfully.",
        )

        self.stock_batch.refresh_from_db()
        order.refresh_from_db()
        order_item.refresh_from_db()
        self.prescription.refresh_from_db()

        self.assertEqual(dispense.status, Dispense.Status.COMPLETED)
        self.assertEqual(dispense.total_amount, Decimal("1500.00"))
        self.assertEqual(self.stock_batch.quantity_on_hand, 9)
        self.assertEqual(
            order_item.status,
            PharmacyOrderItem.Status.DISPENSED,
        )
        self.assertEqual(order.status, PharmacyOrder.Status.DISPENSED)
        self.assertEqual(self.prescription.status, "completed")

        movement = StockMovement.objects.get(
            movement_type=StockMovement.Types.DISPENSE
        )

        self.assertEqual(movement.quantity, 1)
        self.assertEqual(movement.balance_before, 10)
        self.assertEqual(movement.balance_after, 9)
        self.assertEqual(movement.created_by, self.pharmacist_user)

        notification = Notification.objects.get(
            recipient=self.doctor_user,
            notification_type=Notification.Types.PHARMACY,
        )

        self.assertEqual(notification.title, "Prescription Dispensed")
        self.assertIn(str(self.prescription.pk), notification.message)
        self.assertIn(self.patient.full_name, notification.message)
        self.assertIn(self.pharmacy.name, notification.message)
        self.assertEqual(
            notification.action_url,
            self.prescription.get_absolute_url(),
        )
        self.assertFalse(notification.is_read)

    def test_excess_quantity_is_rejected_without_stock_change(self):
        order = self._accepted_order()
        order_item = order.items.get()

        with self.assertRaises(ValidationError):
            complete_order_dispense(
                order=order,
                pharmacist_assignment=self.pharmacist_assignment,
                allocations=[
                    {
                        "order_item": order_item,
                        "stock_batch": self.stock_batch,
                        "quantity": 2,
                    }
                ],
            )

        self.stock_batch.refresh_from_db()

        self.assertEqual(self.stock_batch.quantity_on_hand, 10)
        self.assertEqual(Dispense.objects.count(), 0)
        self.assertEqual(StockMovement.objects.count(), 0)

    def test_expired_stock_cannot_be_dispensed(self):
        order = self._accepted_order()
        order_item = order.items.get()

        expired_batch = StockBatch.objects.create(
            inventory=self.inventory,
            batch_number="EXPIRED-WORKFLOW",
            expiry_date=timezone.localdate() - timedelta(days=1),
            received_quantity=5,
            purchase_price=Decimal("1000.00"),
            selling_price=Decimal("1500.00"),
            is_active=True,
        )

        with self.assertRaises(ValidationError):
            complete_order_dispense(
                order=order,
                pharmacist_assignment=self.pharmacist_assignment,
                allocations=[
                    {
                        "order_item": order_item,
                        "stock_batch": expired_batch,
                        "quantity": 1,
                    }
                ],
            )

        expired_batch.refresh_from_db()

        self.assertEqual(expired_batch.quantity_on_hand, 5)
        self.assertEqual(Dispense.objects.count(), 0)

    def test_partial_dispense_keeps_order_open(self):
        order = self._accepted_order()
        order_item = order.items.get()

        order_item.requested_quantity = 2
        order_item.save()

        complete_order_dispense(
            order=order,
            pharmacist_assignment=self.pharmacist_assignment,
            allocations=[
                {
                    "order_item": order_item,
                    "stock_batch": self.stock_batch,
                    "quantity": 1,
                }
            ],
        )

        self.stock_batch.refresh_from_db()
        order.refresh_from_db()
        order_item.refresh_from_db()
        self.prescription.refresh_from_db()

        self.assertEqual(self.stock_batch.quantity_on_hand, 9)
        self.assertEqual(
            order_item.status,
            PharmacyOrderItem.Status.PARTIAL,
        )
        self.assertEqual(order_item.remaining_quantity, 1)
        self.assertEqual(
            order.status,
            PharmacyOrder.Status.PARTIALLY_DISPENSED,
        )
        self.assertEqual(self.prescription.status, "sent")

    def test_void_dispense_restores_stock(self):
        order = self._accepted_order()
        order_item = order.items.get()

        dispense = complete_order_dispense(
            order=order,
            pharmacist_assignment=self.pharmacist_assignment,
            allocations=[
                {
                    "order_item": order_item,
                    "stock_batch": self.stock_batch,
                    "quantity": 1,
                }
            ],
        )

        voided_dispense = void_completed_dispense(
            dispense=dispense,
            pharmacist_assignment=self.pharmacist_assignment,
            reason="Dispensing entry was created by mistake.",
        )

        self.stock_batch.refresh_from_db()
        order.refresh_from_db()
        order_item.refresh_from_db()
        self.prescription.refresh_from_db()

        self.assertEqual(voided_dispense.status, Dispense.Status.VOIDED)
        self.assertEqual(self.stock_batch.quantity_on_hand, 10)
        self.assertEqual(order.status, PharmacyOrder.Status.IN_PROGRESS)
        self.assertEqual(
            order_item.status,
            PharmacyOrderItem.Status.AVAILABLE,
        )
        self.assertEqual(self.prescription.status, "sent")

        movement_types = set(
            StockMovement.objects.values_list(
                "movement_type",
                flat=True,
            )
        )

        self.assertEqual(
            movement_types,
            {
                StockMovement.Types.DISPENSE,
                StockMovement.Types.PATIENT_RETURN,
            },
        )
