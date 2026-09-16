from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from accounts.tests.permission_utils import apply_role_permissions
from doctor.models import Doctor


User = get_user_model()


def create_user(email, password="pass1234", role="patient", **kwargs):
    return User.objects.create_user(
        email=email,
        password=password,
        role=role,
        **kwargs,
    )


def create_doctor_user(email="doc@example.com"):
    user = create_user(email=email, role="doctor")
    Doctor.objects.create(
        user=user,
        full_name="Dr. Test",
    )
    apply_role_permissions(user)
    return user


class DoctorTemplateTests(TestCase):
    def setUp(self):
        self.dashboard_url = reverse("doctor:dashboard")
        self.doctor_user = create_doctor_user()
        self.secretary_user = create_user(
            email="sec@example.com",
            role="secretary",
        )
        self.password = "pass1234"

    def test_dashboard_uses_correct_template(self):
        self.client.login(
            email=self.doctor_user.email,
            password=self.password,
        )

        response = self.client.get(self.dashboard_url)

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(
            response,
            "doctor/doctor_dashboard.html",
        )

    def test_doctor_sees_expected_buttons(self):
        self.client.login(
            email=self.doctor_user.email,
            password=self.password,
        )

        response = self.client.get(self.dashboard_url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Prescriptions")
        self.assertContains(response, "Patients")
        self.assertContains(response, "Queue")
        self.assertNotContains(response, "Call Next")

    def test_secretary_cannot_see_doctor_dashboard(self):
        self.client.login(
            email=self.secretary_user.email,
            password=self.password,
        )

        response = self.client.get(self.dashboard_url)

        self.assertEqual(response.status_code, 403)

    def test_context_data_present(self):
        self.client.login(
            email=self.doctor_user.email,
            password=self.password,
        )

        response = self.client.get(self.dashboard_url)

        self.assertEqual(response.status_code, 200)
        self.assertIn("stats", response.context)
        self.assertIn(
            "prescription_count",
            response.context["stats"],
        )