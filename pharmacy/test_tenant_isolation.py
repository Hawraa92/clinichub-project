from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from hospital.models import (
    Branch,
    Hospital,
    StaffAssignment,
)
from pharmacy.models import (
    Medicine,
    Pharmacy,
    PharmacyInventory,
    PharmacyStaffAssignment,
    StockBatch,
)
from pharmacy.test_permission_utils import (
    apply_role_permissions,
)


User = get_user_model()


class PharmacyTenantIsolationTests(TestCase):
    """
    Ensure a pharmacist can access only the pharmacy,
    medicines, inventory, and batches assigned to them.
    """

    password = "StrongTestPass123!"

    def setUp(self):
        self.client = Client()

        self.hospital_a = Hospital.objects.create(
            name="Pharmacy Isolation Hospital A",
            code="PH-ISO-HOSP-A",
            is_active=True,
        )
        self.branch_a = Branch.objects.create(
            hospital=self.hospital_a,
            name="Pharmacy Branch A",
            code="PH-ISO-A",
            is_active=True,
        )

        self.hospital_b = Hospital.objects.create(
            name="Pharmacy Isolation Hospital B",
            code="PH-ISO-HOSP-B",
            is_active=True,
        )
        self.branch_b = Branch.objects.create(
            hospital=self.hospital_b,
            name="Pharmacy Branch B",
            code="PH-ISO-B",
            is_active=True,
        )

        self.pharmacy_a = Pharmacy.objects.create(
            branch=self.branch_a,
            name="Assigned Pharmacy A",
            code="PH-A",
            pharmacy_type=Pharmacy.Types.CENTRAL,
            is_active=True,
        )
        self.pharmacy_b = Pharmacy.objects.create(
            branch=self.branch_b,
            name="Foreign Pharmacy B",
            code="PH-B",
            pharmacy_type=Pharmacy.Types.CENTRAL,
            is_active=True,
        )

        self.pharmacist_a = self._create_pharmacist(
            email="pharmacist-a@test.com",
            pharmacy=self.pharmacy_a,
            hospital=self.hospital_a,
            branch=self.branch_a,
        )
        self.pharmacist_b = self._create_pharmacist(
            email="pharmacist-b@test.com",
            pharmacy=self.pharmacy_b,
            hospital=self.hospital_b,
            branch=self.branch_b,
        )

        self.medicine_a = Medicine.objects.create(
            hospital=self.hospital_a,
            code="MED-A",
            generic_name="Visible Medicine A",
            brand_name="Visible Brand A",
            strength="500 mg",
            dosage_form=Medicine.DosageForms.TABLET,
            dispensing_unit="tablet",
            is_active=True,
        )
        self.medicine_b = Medicine.objects.create(
            hospital=self.hospital_b,
            code="MED-B",
            generic_name="Hidden Medicine B",
            brand_name="Hidden Brand B",
            strength="250 mg",
            dosage_form=Medicine.DosageForms.TABLET,
            dispensing_unit="tablet",
            is_active=True,
        )

        self.inventory_a = PharmacyInventory.objects.create(
            pharmacy=self.pharmacy_a,
            medicine=self.medicine_a,
            reorder_level=5,
            target_stock=50,
            is_active=True,
        )
        self.inventory_b = PharmacyInventory.objects.create(
            pharmacy=self.pharmacy_b,
            medicine=self.medicine_b,
            reorder_level=5,
            target_stock=50,
            is_active=True,
        )

        expiry = timezone.localdate() + timedelta(days=365)

        self.batch_a = StockBatch.objects.create(
            inventory=self.inventory_a,
            batch_number="VISIBLE-BATCH-A",
            expiry_date=expiry,
            received_quantity=20,
            quantity_on_hand=20,
            purchase_price="1000.00",
            selling_price="1500.00",
            is_active=True,
        )
        self.batch_b = StockBatch.objects.create(
            inventory=self.inventory_b,
            batch_number="HIDDEN-BATCH-B",
            expiry_date=expiry,
            received_quantity=30,
            quantity_on_hand=30,
            purchase_price="900.00",
            selling_price="1400.00",
            is_active=True,
        )

        self.client.force_login(self.pharmacist_a)

    def _create_pharmacist(
        self,
        *,
        email,
        pharmacy,
        hospital,
        branch,
    ):
        user = User.objects.create_user(
            email=email,
            password=self.password,
            role="pharmacist",
            is_approved=True,
        )
        apply_role_permissions(user)

        staff_assignment = StaffAssignment.objects.create(
            user=user,
            hospital=hospital,
            branch=branch,
            role=StaffAssignment.Roles.PHARMACIST,
            is_primary=True,
            is_active=True,
        )

        PharmacyStaffAssignment.objects.create(
            pharmacy=pharmacy,
            staff_assignment=staff_assignment,
            is_manager=True,
            is_active=True,
        )

        return user

    def test_dashboard_lists_only_assigned_pharmacy(self):
        response = self.client.get(
            reverse("pharmacy:dashboard")
        )

        self.assertEqual(response.status_code, 200)

        visible_ids = {
            pharmacy.pk
            for pharmacy in response.context["pharmacies"]
        }

        self.assertEqual(
            visible_ids,
            {self.pharmacy_a.pk},
        )

    def test_inventory_lists_only_assigned_pharmacy(self):
        response = self.client.get(
            reverse("pharmacy:inventory")
        )

        self.assertEqual(response.status_code, 200)

        visible_ids = {
            inventory.pk
            for inventory
            in response.context["page_obj"].object_list
        }

        self.assertEqual(
            visible_ids,
            {self.inventory_a.pk},
        )

    def test_medicines_list_contains_only_assigned_hospital(self):
        response = self.client.get(
            reverse("pharmacy:medicines")
        )

        self.assertEqual(response.status_code, 200)

        visible_ids = {
            medicine.pk
            for medicine
            in response.context["page_obj"].object_list
        }

        self.assertEqual(
            visible_ids,
            {self.medicine_a.pk},
        )

    def test_batches_list_contains_only_assigned_pharmacy(self):
        response = self.client.get(
            reverse("pharmacy:batches")
        )

        self.assertEqual(response.status_code, 200)

        visible_ids = {
            batch.pk
            for batch
            in response.context["page_obj"].object_list
        }

        self.assertEqual(
            visible_ids,
            {self.batch_a.pk},
        )

    def test_cannot_edit_other_hospital_medicine(self):
        response = self.client.get(
            reverse(
                "pharmacy:medicine_edit",
                kwargs={"pk": self.medicine_b.pk},
            )
        )

        self.assertEqual(response.status_code, 404)

    def test_cannot_receive_stock_for_other_pharmacy(self):
        before_count = StockBatch.objects.count()

        response = self.client.post(
            reverse("pharmacy:receive_stock"),
            {
                "inventory": self.inventory_b.pk,
                "batch_number": "ILLEGAL-FOREIGN-BATCH",
                "expiry_date": (
                    timezone.localdate()
                    + timedelta(days=500)
                ).isoformat(),
                "received_quantity": 99,
                "purchase_price": "500.00",
                "selling_price": "700.00",
                "supplier_name": "Foreign Supplier",
            },
        )

        self.assertEqual(response.status_code, 200)

        self.assertEqual(
            StockBatch.objects.count(),
            before_count,
        )

        self.assertFalse(
            StockBatch.objects.filter(
                batch_number="ILLEGAL-FOREIGN-BATCH"
            ).exists()
        )
