from types import SimpleNamespace

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import Client, TestCase
from django.urls import reverse

from hospital.models import (
    Branch,
    Hospital,
    StaffAssignment,
)
from pharmacy.access import (
    accessible_pharmacies,
    is_pharmacy_portal_user,
    is_platform_admin,
    user_can_manage_prescription,
    user_can_view_order,
)
from pharmacy.models import (
    Pharmacy,
    PharmacyStaffAssignment,
)


User = get_user_model()


class PharmacyAccessSecurityTests(TestCase):
    password = "StrongPharmacyPass123!"

    def setUp(self):
        self.client = Client()

        self.hospital_a = Hospital.objects.create(
            name="Access Hospital A",
            code="PH-ACCESS-A",
            is_active=True,
        )
        self.hospital_b = Hospital.objects.create(
            name="Access Hospital B",
            code="PH-ACCESS-B",
            is_active=True,
        )

        self.branch_a1 = Branch.objects.create(
            hospital=self.hospital_a,
            name="Access Branch A1",
            code="PH-A1",
            is_active=True,
        )
        self.branch_a2 = Branch.objects.create(
            hospital=self.hospital_a,
            name="Access Branch A2",
            code="PH-A2",
            is_active=True,
        )
        self.branch_b1 = Branch.objects.create(
            hospital=self.hospital_b,
            name="Access Branch B1",
            code="PH-B1",
            is_active=True,
        )

        self.pharmacy_a1 = Pharmacy.objects.create(
            branch=self.branch_a1,
            name="Pharmacy A1",
            code="ACCESS-PH-A1",
            pharmacy_type=Pharmacy.Types.CENTRAL,
            is_active=True,
        )
        self.pharmacy_a2 = Pharmacy.objects.create(
            branch=self.branch_a2,
            name="Pharmacy A2",
            code="ACCESS-PH-A2",
            pharmacy_type=Pharmacy.Types.CENTRAL,
            is_active=True,
        )
        self.pharmacy_b1 = Pharmacy.objects.create(
            branch=self.branch_b1,
            name="Pharmacy B1",
            code="ACCESS-PH-B1",
            pharmacy_type=Pharmacy.Types.CENTRAL,
            is_active=True,
        )

        self.superuser = User.objects.create_superuser(
            email="pharmacy-platform@test.com",
            password=self.password,
        )

        self.unassigned_admin = User.objects.create_user(
            email="pharmacy-unassigned-admin@test.com",
            password=self.password,
            role="admin",
            is_approved=True,
        )

        self.hospital_admin_a = User.objects.create_user(
            email="pharmacy-hospital-admin-a@test.com",
            password=self.password,
            role="admin",
            is_approved=True,
        )
        StaffAssignment.objects.create(
            user=self.hospital_admin_a,
            hospital=self.hospital_a,
            role=StaffAssignment.Roles.HOSPITAL_ADMIN,
            is_primary=True,
            is_active=True,
        )

        self.branch_admin_a1 = User.objects.create_user(
            email="pharmacy-branch-admin-a1@test.com",
            password=self.password,
            role="admin",
            is_approved=True,
        )
        StaffAssignment.objects.create(
            user=self.branch_admin_a1,
            hospital=self.hospital_a,
            branch=self.branch_a1,
            role=StaffAssignment.Roles.HOSPITAL_ADMIN,
            is_primary=True,
            is_active=True,
        )

        self.pharmacist_b = User.objects.create_user(
            email="pharmacy-pharmacist-b@test.com",
            password=self.password,
            role="pharmacist",
            is_approved=True,
        )
        pharmacist_staff = StaffAssignment.objects.create(
            user=self.pharmacist_b,
            hospital=self.hospital_b,
            branch=self.branch_b1,
            role=StaffAssignment.Roles.PHARMACIST,
            is_primary=True,
            is_active=True,
        )
        PharmacyStaffAssignment.objects.create(
            pharmacy=self.pharmacy_b1,
            staff_assignment=pharmacist_staff,
            is_manager=True,
            is_active=True,
        )

        view_permission = Permission.objects.get(
            content_type__app_label="pharmacy",
            codename="view_pharmacy",
        )

        for user in (
            self.unassigned_admin,
            self.hospital_admin_a,
            self.branch_admin_a1,
            self.pharmacist_b,
        ):
            user.user_permissions.add(view_permission)
            self._clear_permission_cache(user)

    @staticmethod
    def _clear_permission_cache(user):
        for attribute in (
            "_perm_cache",
            "_user_perm_cache",
            "_group_perm_cache",
        ):
            user.__dict__.pop(attribute, None)

    @staticmethod
    def _ids(queryset):
        return set(
            queryset.values_list(
                "pk",
                flat=True,
            )
        )

    def test_only_superuser_is_platform_admin(self):
        self.assertTrue(
            is_platform_admin(self.superuser)
        )
        self.assertFalse(
            is_platform_admin(self.unassigned_admin)
        )
        self.assertFalse(
            is_platform_admin(self.hospital_admin_a)
        )

    def test_unassigned_admin_has_no_pharmacy_scope(self):
        self.assertFalse(
            is_pharmacy_portal_user(
                self.unassigned_admin
            )
        )
        self.assertEqual(
            self._ids(
                accessible_pharmacies(
                    self.unassigned_admin
                )
            ),
            set(),
        )

    def test_hospital_admin_sees_only_own_hospital(self):
        self.assertEqual(
            self._ids(
                accessible_pharmacies(
                    self.hospital_admin_a
                )
            ),
            {
                self.pharmacy_a1.pk,
                self.pharmacy_a2.pk,
            },
        )

    def test_branch_admin_sees_only_assigned_branch(self):
        self.assertEqual(
            self._ids(
                accessible_pharmacies(
                    self.branch_admin_a1
                )
            ),
            {
                self.pharmacy_a1.pk,
            },
        )

    def test_pharmacist_sees_only_assigned_pharmacy(self):
        self.assertEqual(
            self._ids(
                accessible_pharmacies(
                    self.pharmacist_b
                )
            ),
            {
                self.pharmacy_b1.pk,
            },
        )

    def test_superuser_sees_all_pharmacies(self):
        self.assertEqual(
            self._ids(
                accessible_pharmacies(
                    self.superuser
                )
            ),
            {
                self.pharmacy_a1.pk,
                self.pharmacy_a2.pk,
                self.pharmacy_b1.pk,
            },
        )

    def test_unassigned_admin_dashboard_is_forbidden(self):
        self.client.force_login(
            self.unassigned_admin
        )

        response = self.client.get(
            reverse("pharmacy:dashboard")
        )

        self.assertEqual(
            response.status_code,
            403,
        )

    def test_hospital_admin_dashboard_is_tenant_scoped(self):
        self.client.force_login(
            self.hospital_admin_a
        )

        response = self.client.get(
            reverse("pharmacy:dashboard")
        )

        self.assertEqual(
            response.status_code,
            200,
        )

        visible_ids = {
            pharmacy.pk
            for pharmacy in response.context[
                "pharmacies"
            ]
        }

        self.assertEqual(
            visible_ids,
            {
                self.pharmacy_a1.pk,
                self.pharmacy_a2.pk,
            },
        )

    def test_admin_cannot_view_foreign_pharmacy_order(self):
        foreign_order = SimpleNamespace(
            pharmacy_id=self.pharmacy_b1.pk,
            prescription=SimpleNamespace(
                doctor=None,
            ),
        )

        self.assertFalse(
            user_can_view_order(
                self.hospital_admin_a,
                foreign_order,
            )
        )
        self.assertTrue(
            user_can_view_order(
                self.superuser,
                foreign_order,
            )
        )

    def test_admin_prescription_management_is_location_scoped(self):
        own_prescription = SimpleNamespace(
            doctor=None,
            appointment=SimpleNamespace(
                hospital_id=self.hospital_a.pk,
                branch_id=self.branch_a2.pk,
            ),
        )
        foreign_prescription = SimpleNamespace(
            doctor=None,
            appointment=SimpleNamespace(
                hospital_id=self.hospital_b.pk,
                branch_id=self.branch_b1.pk,
            ),
        )

        self.assertTrue(
            user_can_manage_prescription(
                self.hospital_admin_a,
                own_prescription,
            )
        )
        self.assertFalse(
            user_can_manage_prescription(
                self.hospital_admin_a,
                foreign_prescription,
            )
        )
        self.assertFalse(
            user_can_manage_prescription(
                self.branch_admin_a1,
                own_prescription,
            )
        )
