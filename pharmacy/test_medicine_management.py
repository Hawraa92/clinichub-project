from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from pharmacy.models import Medicine, PharmacyInventory
from pharmacy.services import create_standalone_pharmacy

from .test_permission_utils import apply_role_permissions


User = get_user_model()


class MedicineManagementViewsTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="medicine.manager@example.com",
            password="test-password",
            role="pharmacist",
            is_approved=True,
        )
        self.pharmacy, self.assignment = create_standalone_pharmacy(
            name="Test Standalone Pharmacy",
            code="TESTMED",
            owner_user=self.user,
        )
        apply_role_permissions(self.user)
        self.client.force_login(self.user)

    def _medicine_payload(self):
        return {
            "pharmacy": str(self.pharmacy.pk),
            "code": "MED-001",
            "barcode": "1234567890123",
            "generic_name": "Paracetamol",
            "brand_name": "Panadol",
            "strength": "500 mg",
            "dosage_form": Medicine.DosageForms.TABLET,
            "dispensing_unit": "tablet",
            "manufacturer": "Test Manufacturer",
            "description": "Test medicine",
            "requires_prescription": "on",
            "is_active": "on",
            "add_to_inventory": "on",
            "reorder_level": "10",
            "target_stock": "100",
        }

    def test_manager_sees_add_medicine_button(self):
        response = self.client.get(reverse("pharmacy:medicines"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Add medicine")

    def test_create_medicine_and_inventory(self):
        response = self.client.post(
            reverse("pharmacy:medicine_create"),
            self._medicine_payload(),
        )

        self.assertRedirects(response, reverse("pharmacy:medicines"))

        medicine = Medicine.objects.get(
            hospital=self.pharmacy.branch.hospital,
            code="MED-001",
        )
        inventory = PharmacyInventory.objects.get(
            pharmacy=self.pharmacy,
            medicine=medicine,
        )

        self.assertEqual(medicine.generic_name, "Paracetamol")
        self.assertEqual(inventory.reorder_level, 10)
        self.assertEqual(inventory.target_stock, 100)
        self.assertTrue(inventory.is_active)

    def test_duplicate_code_is_rejected(self):
        self.client.post(
            reverse("pharmacy:medicine_create"),
            self._medicine_payload(),
        )

        duplicate = self._medicine_payload()
        duplicate["barcode"] = "9999999999999"
        duplicate["brand_name"] = "Another Brand"

        response = self.client.post(
            reverse("pharmacy:medicine_create"),
            duplicate,
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            "This medicine code already exists",
        )
        self.assertEqual(
            Medicine.objects.filter(code="MED-001").count(),
            1,
        )

    def test_toggle_deactivates_medicine_and_inventory(self):
        self.client.post(
            reverse("pharmacy:medicine_create"),
            self._medicine_payload(),
        )
        medicine = Medicine.objects.get(code="MED-001")

        response = self.client.post(
            reverse(
                "pharmacy:medicine_toggle_active",
                kwargs={"pk": medicine.pk},
            )
        )

        self.assertRedirects(response, reverse("pharmacy:medicines"))
        medicine.refresh_from_db()
        inventory = PharmacyInventory.objects.get(
            pharmacy=self.pharmacy,
            medicine=medicine,
        )
        self.assertFalse(medicine.is_active)
        self.assertFalse(inventory.is_active)
