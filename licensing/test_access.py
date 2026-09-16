from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import Client, TestCase
from django.urls import reverse

from hospital.models import Branch, Hospital, StaffAssignment


User = get_user_model()


class LicensingAccessTests(TestCase):
    password = "SyntheticLicensePass123!"

    def setUp(self):
        self.client = Client()
        self.hospital = Hospital.objects.create(
            name="Synthetic Licensing Hospital",
            code="SYN-LIC-HOSP",
            is_active=True,
        )
        self.branch = Branch.objects.create(
            hospital=self.hospital,
            name="Synthetic Licensing Branch",
            code="SYN-LIC-BRANCH",
            is_active=True,
        )

        self.superuser = User.objects.create_superuser(
            email="synthetic-license-superuser@example.test",
            password=self.password,
        )
        self.normal_admin = User.objects.create_user(
            email="synthetic-license-admin@example.test",
            password=self.password,
            role="admin",
            is_approved=True,
        )
        self.hospital_admin = User.objects.create_user(
            email="synthetic-license-hospital-admin@example.test",
            password=self.password,
            role="admin",
            is_approved=True,
        )
        self.branch_admin = User.objects.create_user(
            email="synthetic-license-branch-admin@example.test",
            password=self.password,
            role="admin",
            is_approved=True,
        )
        self.permitted_admin = User.objects.create_user(
            email="synthetic-license-permitted@example.test",
            password=self.password,
            role="admin",
            is_approved=True,
        )

        StaffAssignment.objects.create(
            user=self.hospital_admin,
            hospital=self.hospital,
            role=StaffAssignment.Roles.HOSPITAL_ADMIN,
            is_primary=True,
            is_active=True,
        )
        StaffAssignment.objects.create(
            user=self.branch_admin,
            hospital=self.hospital,
            branch=self.branch,
            role=StaffAssignment.Roles.HOSPITAL_ADMIN,
            is_primary=True,
            is_active=True,
        )

        permission = Permission.objects.get(
            content_type__app_label="licensing",
            codename="change_licenserecord",
        )
        self.permitted_admin.user_permissions.add(permission)
        self._clear_permission_cache(self.permitted_admin)

    @staticmethod
    def _clear_permission_cache(user):
        for name in ("_perm_cache", "_user_perm_cache", "_group_perm_cache"):
            user.__dict__.pop(name, None)

    @staticmethod
    def _license_record():
        return SimpleNamespace(license_id="synthetic-license-id")

    def _assert_activation_denied(self, user):
        self.client.force_login(user)
        with patch("licensing.views.install_license") as install_license:
            response = self.client.post(
                reverse("licensing:activate"),
                {"license_token": "CHL1.synthetic.token"},
            )

        self.assertEqual(response.status_code, 403)
        install_license.assert_not_called()

    def _assert_sync_denied(self, user):
        self.client.force_login(user)
        with patch("licensing.views.synchronize_license") as synchronize_license:
            response = self.client.post(reverse("licensing:sync"))

        self.assertEqual(response.status_code, 403)
        synchronize_license.assert_not_called()

    def test_normal_admin_cannot_activate_license(self):
        self._assert_activation_denied(self.normal_admin)

    def test_hospital_admin_cannot_activate_license(self):
        self._assert_activation_denied(self.hospital_admin)

    def test_branch_admin_cannot_activate_license(self):
        self._assert_activation_denied(self.branch_admin)

    def test_normal_admin_cannot_synchronize_license(self):
        self._assert_sync_denied(self.normal_admin)

    def test_hospital_admin_cannot_synchronize_license(self):
        self._assert_sync_denied(self.hospital_admin)

    def test_branch_admin_cannot_synchronize_license(self):
        self._assert_sync_denied(self.branch_admin)

    def test_superuser_can_activate_license(self):
        self.client.force_login(self.superuser)
        with patch(
            "licensing.views.install_license",
            return_value=self._license_record(),
        ) as install_license:
            response = self.client.post(
                reverse("licensing:activate"),
                {"license_token": "CHL1.synthetic.token"},
            )

        self.assertRedirects(response, reverse("licensing:status"))
        install_license.assert_called_once()
        self.assertEqual(
            install_license.call_args.kwargs["actor"],
            self.superuser,
        )

    def test_explicitly_permitted_admin_can_activate_license(self):
        self.client.force_login(self.permitted_admin)
        with patch(
            "licensing.views.install_license",
            return_value=self._license_record(),
        ) as install_license:
            response = self.client.post(
                reverse("licensing:activate"),
                {"license_token": "CHL1.synthetic.token"},
            )

        self.assertRedirects(response, reverse("licensing:status"))
        install_license.assert_called_once()

    def test_superuser_can_synchronize_license(self):
        self.client.force_login(self.superuser)
        with patch(
            "licensing.views.synchronize_license",
            return_value=self._license_record(),
        ) as synchronize_license:
            response = self.client.post(reverse("licensing:sync"))

        self.assertRedirects(response, reverse("licensing:status"))
        synchronize_license.assert_called_once_with()

    def test_explicitly_permitted_admin_can_synchronize_license(self):
        self.client.force_login(self.permitted_admin)
        with patch(
            "licensing.views.synchronize_license",
            return_value=self._license_record(),
        ) as synchronize_license:
            response = self.client.post(reverse("licensing:sync"))

        self.assertRedirects(response, reverse("licensing:status"))
        synchronize_license.assert_called_once_with()
