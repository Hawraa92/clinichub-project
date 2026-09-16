import shutil
import tempfile
from datetime import date, timedelta

from appointments.models import Appointment
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from doctor.models import Doctor
from hospital.models import Branch, Hospital, StaffAssignment
from patient.models import Patient
from prescription.models import Medication, Prescription

from .models import (
    Medicine,
    Pharmacy,
    PharmacyInventory,
    PharmacyOrder,
    PharmacyStaffAssignment,
    StockBatch,
    StockMovement,
)
from .services import send_prescription_to_pharmacy

from .test_permission_utils import apply_role_permissions


User = get_user_model()


class PharmacyViewTests(TestCase):
    def setUp(self):
        self.media_root = tempfile.mkdtemp()
        self.media_override = override_settings(MEDIA_ROOT=self.media_root)
        self.media_override.enable()

        self.hospital = Hospital.objects.create(
            name="UI Test Hospital",
            code="UI-HOSP",
            is_active=True,
        )
        self.branch = Branch.objects.create(
            hospital=self.hospital,
            name="UI Test Branch",
            code="UI-BR",
            is_active=True,
        )

        self.doctor_user = User.objects.create_user(
            email="ui-doctor@example.com",
            password="testpass123",
            role="doctor",
            is_approved=True,
        )
        self.doctor = Doctor.objects.create(
            user=self.doctor_user,
            specialty="General Medicine",
        )
        StaffAssignment.objects.create(
            user=self.doctor_user,
            hospital=self.hospital,
            branch=self.branch,
            role=StaffAssignment.Roles.DOCTOR,
            is_primary=True,
            is_active=True,
        )

        self.patient_user = User.objects.create_user(
            email="ui-patient@example.com",
            password="testpass123",
            role="patient",
            is_approved=True,
        )
        self.patient, created = Patient.objects.get_or_create(
            user=self.patient_user,
            defaults={
                "full_name": "UI Test Patient",
                "date_of_birth": date(1990, 1, 1),
            },
        )
        if not created:
            self.patient.full_name = "UI Test Patient"
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
            diagnosis="UI test diagnosis",
        )
        Medication.objects.create(
            prescription=self.prescription,
            name="Panadol",
            dosage="500 mg twice daily",
        )

        self.pharmacy = Pharmacy.objects.create(
            branch=self.branch,
            name="UI Test Pharmacy",
            code="UI-PH",
            pharmacy_type=Pharmacy.Types.CENTRAL,
            is_active=True,
        )
        self.medicine = Medicine.objects.create(
            hospital=self.hospital,
            code="UI-PANADOL",
            barcode="UI123456789",
            generic_name="Paracetamol",
            brand_name="Panadol",
            strength="500 mg",
            dosage_form=Medicine.DosageForms.TABLET,
            dispensing_unit="tablet",
            is_active=True,
        )
        self.inventory = PharmacyInventory.objects.create(
            pharmacy=self.pharmacy,
            medicine=self.medicine,
            reorder_level=2,
            target_stock=20,
            is_active=True,
        )
        self.batch = StockBatch.objects.create(
            inventory=self.inventory,
            batch_number="UI-BATCH",
            expiry_date=timezone.localdate() + timedelta(days=365),
            received_quantity=10,
            purchase_price="1000.00",
            selling_price="1500.00",
            is_active=True,
        )

        self.pharmacist_user = User.objects.create_user(
            email="ui-pharmacist@example.com",
            password="testpass123",
            role="pharmacist",
            is_approved=True,
        )
        hospital_assignment = StaffAssignment.objects.create(
            user=self.pharmacist_user,
            hospital=self.hospital,
            branch=self.branch,
            role=StaffAssignment.Roles.PHARMACIST,
            is_primary=True,
            is_active=True,
        )
        self.pharmacist_assignment = PharmacyStaffAssignment.objects.create(
            pharmacy=self.pharmacy,
            staff_assignment=hospital_assignment,
            is_manager=True,
            is_active=True,
        )

        # Use ClinicHub's production permission presets in tests.
        apply_role_permissions(self.doctor_user)
        apply_role_permissions(self.pharmacist_user)

    def tearDown(self):
        self.media_override.disable()
        shutil.rmtree(self.media_root, ignore_errors=True)
        super().tearDown()

    def _send_order(self):
        return send_prescription_to_pharmacy(
            prescription=self.prescription,
            pharmacy=self.pharmacy,
            sent_by=self.doctor_user,
        )

    def test_dashboard_requires_login(self):
        response = self.client.get(reverse("pharmacy:dashboard"))
        self.assertEqual(response.status_code, 302)

    def test_non_pharmacist_cannot_open_dashboard(self):
        self.client.force_login(self.doctor_user)
        response = self.client.get(reverse("pharmacy:dashboard"))
        self.assertEqual(response.status_code, 403)

    def test_pharmacist_can_open_dashboard(self):
        self.client.force_login(self.pharmacist_user)
        response = self.client.get(reverse("pharmacy:dashboard"))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "pharmacy/dashboard.html")

    def test_doctor_can_open_send_prescription_page(self):
        self.client.force_login(self.doctor_user)
        response = self.client.get(
            reverse(
                "pharmacy:send_prescription",
                kwargs={"prescription_id": self.prescription.pk},
            )
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.pharmacy.name)

    def test_doctor_can_send_prescription_from_form(self):
        self.client.force_login(self.doctor_user)
        response = self.client.post(
            reverse(
                "pharmacy:send_prescription",
                kwargs={"prescription_id": self.prescription.pk},
            ),
            {
                "pharmacy": self.pharmacy.pk,
                "priority": PharmacyOrder.Priority.URGENT,
                "doctor_notes": "Urgent UI test order.",
            },
        )
        order = PharmacyOrder.objects.get(prescription=self.prescription)
        self.assertRedirects(
            response,
            reverse("pharmacy:order_detail", kwargs={"pk": order.pk}),
        )
        self.assertEqual(order.priority, PharmacyOrder.Priority.URGENT)

    def test_pharmacist_can_accept_order(self):
        order = self._send_order()
        self.client.force_login(self.pharmacist_user)
        response = self.client.post(
            reverse("pharmacy:accept_order", kwargs={"pk": order.pk})
        )
        self.assertRedirects(
            response,
            reverse("pharmacy:order_detail", kwargs={"pk": order.pk}),
        )
        order.refresh_from_db()
        self.assertEqual(order.status, PharmacyOrder.Status.ACCEPTED)

    def test_pharmacist_can_receive_stock(self):
        self.client.force_login(self.pharmacist_user)
        response = self.client.post(
            reverse("pharmacy:receive_stock"),
            {
                "inventory": self.inventory.pk,
                "batch_number": "UI-NEW-BATCH",
                "expiry_date": (
                    timezone.localdate() + timedelta(days=500)
                ).isoformat(),
                "received_quantity": 25,
                "purchase_price": "900.00",
                "selling_price": "1400.00",
                "supplier_name": "UI Supplier",
            },
        )
        self.assertRedirects(response, reverse("pharmacy:batches"))
        new_batch = StockBatch.objects.get(batch_number="UI-NEW-BATCH")
        self.assertEqual(new_batch.quantity_on_hand, 25)
        self.assertTrue(
            StockMovement.objects.filter(
                stock_batch=new_batch,
                movement_type=StockMovement.Types.RECEIPT,
            ).exists()
        )

    def test_unrelated_patient_cannot_view_order(self):
        order = self._send_order()
        self.client.force_login(self.patient_user)
        response = self.client.get(
            reverse("pharmacy:order_detail", kwargs={"pk": order.pk})
        )
        self.assertEqual(response.status_code, 403)
