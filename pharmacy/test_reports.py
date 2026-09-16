from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from pharmacy.services import create_standalone_pharmacy

from .test_permission_utils import apply_role_permissions


User = get_user_model()


class PharmacyReportsTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="reports.manager@example.com",
            password="test-password",
            role="pharmacist",
            is_approved=True,
        )
        self.pharmacy, self.assignment = create_standalone_pharmacy(
            name="Reports Test Pharmacy",
            code="REPORTS01",
            owner_user=self.user,
        )
        apply_role_permissions(self.user)
        self.client.force_login(self.user)

    def test_reports_dashboard_is_available(self):
        response = self.client.get(reverse("pharmacy:reports"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Pharmacy Reports")
        self.assertContains(response, "Gross profit")
        self.assertContains(response, "Low stock")

    def test_printable_report_is_available(self):
        response = self.client.get(reverse("pharmacy:reports_print"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "ClinicHub Pharmacy Report")
        self.assertContains(response, "Print / Save PDF")

    def test_sales_csv_uses_excel_compatible_utf8(self):
        response = self.client.get(reverse("pharmacy:sales_report_csv"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "text/csv; charset=utf-8")
        self.assertTrue(response.content.startswith(b"\xef\xbb\xbf"))
        self.assertIn(b"Total revenue", response.content)

    def test_inventory_csv_is_available(self):
        response = self.client.get(reverse("pharmacy:inventory_report_csv"))

        self.assertEqual(response.status_code, 200)
        self.assertIn(
            'filename="pharmacy-inventory-',
            response["Content-Disposition"],
        )
        self.assertIn(b"Reorder level", response.content)
