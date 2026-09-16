from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from hospital.models import (
    Branch,
    Hospital,
    StaffAssignment,
)
from pharmacy.models import (
    Pharmacy,
    PharmacySale,
    PharmacyStaffAssignment,
)
from pharmacy.test_permission_utils import (
    apply_role_permissions,
)


User = get_user_model()


class PharmacySaleTenantIsolationTests(TestCase):
    """
    Ensure direct sales and financial actions are isolated
    between separate pharmacies and organizations.
    """

    password = "StrongTestPass123!"

    def setUp(self):
        self.client = Client()

        self.hospital_a = Hospital.objects.create(
            name="Sale Isolation Hospital A",
            code="SALE-ISO-HOSP-A",
            is_active=True,
        )
        self.branch_a = Branch.objects.create(
            hospital=self.hospital_a,
            name="Sale Branch A",
            code="SALE-ISO-A",
            is_active=True,
        )
        self.pharmacy_a = Pharmacy.objects.create(
            branch=self.branch_a,
            name="Assigned Sale Pharmacy A",
            code="SALE-PH-A",
            pharmacy_type=Pharmacy.Types.CENTRAL,
            is_active=True,
        )

        self.hospital_b = Hospital.objects.create(
            name="Sale Isolation Hospital B",
            code="SALE-ISO-HOSP-B",
            is_active=True,
        )
        self.branch_b = Branch.objects.create(
            hospital=self.hospital_b,
            name="Sale Branch B",
            code="SALE-ISO-B",
            is_active=True,
        )
        self.pharmacy_b = Pharmacy.objects.create(
            branch=self.branch_b,
            name="Foreign Sale Pharmacy B",
            code="SALE-PH-B",
            pharmacy_type=Pharmacy.Types.CENTRAL,
            is_active=True,
        )

        (
            self.pharmacist_a,
            self.assignment_a,
        ) = self._create_pharmacist(
            email="sale-pharmacist-a@test.com",
            pharmacy=self.pharmacy_a,
            hospital=self.hospital_a,
            branch=self.branch_a,
        )

        (
            self.pharmacist_b,
            self.assignment_b,
        ) = self._create_pharmacist(
            email="sale-pharmacist-b@test.com",
            pharmacy=self.pharmacy_b,
            hospital=self.hospital_b,
            branch=self.branch_b,
        )

        # Grant void permission so the test reaches tenant isolation
        # instead of being stopped by the global URL permission.
        delete_sale_permission = Permission.objects.get(
            content_type__app_label="pharmacy",
            codename="delete_pharmacysale",
        )
        self.pharmacist_a.user_permissions.add(
            delete_sale_permission
        )

        self.sale_a = PharmacySale.objects.create(
            pharmacy=self.pharmacy_a,
            cashier=self.assignment_a,
            customer_name="Visible Customer A",
            status=PharmacySale.Status.COMPLETED,
            subtotal=Decimal("10000.00"),
            discount_amount=Decimal("0.00"),
            total_amount=Decimal("10000.00"),
            amount_paid=Decimal("0.00"),
            payment_status=(
                PharmacySale.PaymentStatus.UNPAID
            ),
            completed_at=timezone.now(),
            notes="VISIBLE-SALE-A",
        )

        self.sale_b = PharmacySale.objects.create(
            pharmacy=self.pharmacy_b,
            cashier=self.assignment_b,
            customer_name="Hidden Customer B",
            status=PharmacySale.Status.COMPLETED,
            subtotal=Decimal("20000.00"),
            discount_amount=Decimal("0.00"),
            total_amount=Decimal("20000.00"),
            amount_paid=Decimal("0.00"),
            payment_status=(
                PharmacySale.PaymentStatus.UNPAID
            ),
            completed_at=timezone.now(),
            notes="HIDDEN-SALE-B",
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

        pharmacy_assignment = (
            PharmacyStaffAssignment.objects.create(
                pharmacy=pharmacy,
                staff_assignment=staff_assignment,
                is_manager=True,
                is_active=True,
            )
        )

        return user, pharmacy_assignment

    def test_sale_list_contains_only_assigned_pharmacy(self):
        response = self.client.get(
            reverse("pharmacy:sales")
        )

        self.assertEqual(response.status_code, 200)

        visible_ids = {
            sale.pk
            for sale
            in response.context["page_obj"].object_list
        }

        self.assertEqual(
            visible_ids,
            {self.sale_a.pk},
        )

    def test_sale_create_form_lists_only_assigned_pharmacy(self):
        response = self.client.get(
            reverse("pharmacy:sale_create")
        )

        self.assertEqual(response.status_code, 200)

        pharmacy_queryset = (
            response.context["form"]
            .fields["pharmacy"]
            .queryset
        )

        self.assertEqual(
            set(
                pharmacy_queryset.values_list(
                    "pk",
                    flat=True,
                )
            ),
            {self.pharmacy_a.pk},
        )

    def test_can_open_assigned_sale(self):
        response = self.client.get(
            reverse(
                "pharmacy:sale_detail",
                kwargs={"pk": self.sale_a.pk},
            )
        )

        self.assertEqual(response.status_code, 200)

    def test_cannot_open_foreign_sale(self):
        response = self.client.get(
            reverse(
                "pharmacy:sale_detail",
                kwargs={"pk": self.sale_b.pk},
            )
        )

        self.assertEqual(response.status_code, 404)

    def test_cannot_open_foreign_sale_receipt(self):
        response = self.client.get(
            reverse(
                "pharmacy:sale_receipt",
                kwargs={"pk": self.sale_b.pk},
            )
        )

        self.assertEqual(response.status_code, 404)

    def test_cannot_record_payment_for_foreign_sale(self):
        original_amount_paid = self.sale_b.amount_paid

        response = self.client.post(
            reverse(
                "pharmacy:sale_payment",
                kwargs={"pk": self.sale_b.pk},
            ),
            {
                "amount": "5000.00",
                "payment_method": (
                    PharmacySale.PaymentMethod.CASH
                ),
                "transaction_reference": "",
                "notes": "ILLEGAL-FOREIGN-PAYMENT",
            },
        )

        self.assertEqual(response.status_code, 404)

        self.sale_b.refresh_from_db()

        self.assertEqual(
            self.sale_b.amount_paid,
            original_amount_paid,
        )

        self.assertNotIn(
            "ILLEGAL-FOREIGN-PAYMENT",
            self.sale_b.notes,
        )

    def test_cannot_void_foreign_sale(self):
        original_status = self.sale_b.status

        response = self.client.post(
            reverse(
                "pharmacy:sale_void",
                kwargs={"pk": self.sale_b.pk},
            ),
            {
                "reason": "ILLEGAL-FOREIGN-VOID",
            },
        )

        self.assertEqual(response.status_code, 404)

        self.sale_b.refresh_from_db()

        self.assertEqual(
            self.sale_b.status,
            original_status,
        )
        self.assertIsNone(self.sale_b.voided_at)
        self.assertNotIn(
            "ILLEGAL-FOREIGN-VOID",
            self.sale_b.notes,
        )
