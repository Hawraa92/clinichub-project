from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import Client, TestCase
from django.urls import reverse

from hospital.models import (
    Branch,
    Hospital,
    StaffAssignment,
)


User = get_user_model()


class AnalyticsTenantIsolationTests(TestCase):
    """
    Platform superusers may access every hospital.

    A non-superuser hospital administrator may access only
    hospitals covered by an active hospital-admin assignment.
    """

    password = "StrongTestPass123!"

    def setUp(self):
        cache.clear()
        self.client = Client()

        self.hospital_a = Hospital.objects.create(
            name="Analytics Isolation Hospital A",
            code="AN-ISO-HOSP-A",
            is_active=True,
        )
        self.branch_a = Branch.objects.create(
            hospital=self.hospital_a,
            name="Analytics Branch A",
            code="AN-ISO-A",
            is_active=True,
        )

        self.hospital_b = Hospital.objects.create(
            name="Analytics Isolation Hospital B",
            code="AN-ISO-HOSP-B",
            is_active=True,
        )
        self.branch_b = Branch.objects.create(
            hospital=self.hospital_b,
            name="Analytics Branch B",
            code="AN-ISO-B",
            is_active=True,
        )

        # Central ClinicHub owner/platform administrator.
        self.platform_admin = User.objects.create_superuser(
            email="platform-admin@test.com",
            password=self.password,
        )

        # Hospital administrator assigned only to Hospital A.
        self.hospital_admin_a = User.objects.create_user(
            email="hospital-admin-a@test.com",
            password=self.password,
            role="admin",
            is_approved=True,
        )

        StaffAssignment.objects.create(
            user=self.hospital_admin_a,
            hospital=self.hospital_a,
            branch=None,
            role=StaffAssignment.Roles.HOSPITAL_ADMIN,
            is_primary=True,
            is_active=True,
        )

        # An admin-role account with no hospital assignment.
        self.unassigned_admin = User.objects.create_user(
            email="unassigned-admin@test.com",
            password=self.password,
            role="admin",
            is_approved=True,
        )

    def test_platform_superuser_can_access_all_hospitals(self):
        self.client.force_login(self.platform_admin)

        response = self.client.get(
            reverse("analytics:dashboard")
        )

        self.assertEqual(response.status_code, 200)

        visible_hospital_ids = set(
            response.context["hospitals"].values_list(
                "pk",
                flat=True,
            )
        )

        self.assertEqual(
            visible_hospital_ids,
            {
                self.hospital_a.pk,
                self.hospital_b.pk,
            },
        )

        branch_response = self.client.get(
            reverse(
                "analytics:branch_detail",
                args=[self.branch_b.pk],
            )
        )

        self.assertEqual(
            branch_response.status_code,
            200,
        )

    def test_hospital_admin_sees_only_assigned_hospital(self):
        self.client.force_login(self.hospital_admin_a)

        response = self.client.get(
            reverse("analytics:dashboard")
        )

        self.assertEqual(response.status_code, 200)

        visible_hospital_ids = set(
            response.context["hospitals"].values_list(
                "pk",
                flat=True,
            )
        )

        self.assertEqual(
            visible_hospital_ids,
            {self.hospital_a.pk},
        )

        self.assertEqual(
            response.context["selected_hospital"].pk,
            self.hospital_a.pk,
        )

    def test_hospital_admin_cannot_select_other_hospital(self):
        self.client.force_login(self.hospital_admin_a)

        response = self.client.get(
            reverse("analytics:dashboard"),
            {
                "hospital": self.hospital_b.pk,
                "branch": self.branch_b.pk,
            },
        )

        self.assertEqual(response.status_code, 200)

        self.assertEqual(
            response.context["selected_hospital"].pk,
            self.hospital_a.pk,
        )

        self.assertIsNone(
            response.context["selected_branch"]
        )

    def test_hospital_admin_cannot_open_other_hospital_branch(self):
        self.client.force_login(self.hospital_admin_a)

        response = self.client.get(
            reverse(
                "analytics:branch_detail",
                args=[self.branch_b.pk],
            )
        )

        # Hide the existence of the foreign branch.
        self.assertEqual(response.status_code, 404)

    def test_unassigned_admin_cannot_access_analytics(self):
        self.client.force_login(self.unassigned_admin)

        response = self.client.get(
            reverse("analytics:dashboard")
        )

        self.assertEqual(response.status_code, 403)
