# doctor/tests/test_permissions.py
from django.test import TestCase
from django.urls import reverse
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied

from doctor.models import Doctor

User = get_user_model()


def create_user(email, password='pass1234', role='patient', **kwargs):
    """Helper to create a user with a given role."""
    user = User.objects.create_user(email=email, password=password, role=role, **kwargs)
    return user


def create_doctor_user(email='doc@example.com'):
    """Create a user + Doctor profile."""
    user = create_user(email=email, role='doctor')
    Doctor.objects.create(user=user, full_name='Dr. Test')
    return user


class DoctorPermissionTests(TestCase):
    """Permission tests for doctor-only views."""

    def setUp(self):
        # URLs you want to test (change names if different in your project)
        self.dashboard_url = reverse('doctor:dashboard')               # /doctor/dashboard/
        self.patients_url  = reverse('doctor:patients_list')           # e.g. /doctor/patients/
        # أضف أي URLs أخرى للطبيب هنا:
        # self.report_url    = reverse('doctor:reports')

        self.doctor_user = create_doctor_user()
        self.secretary_user = create_user('sec@example.com', role='secretary')
        self.random_user = create_user('rand@example.com', role='patient')  # أو أي دور آخر
        self.password = 'pass1234'

    # ---------- Anonymous ----------
    def test_anonymous_redirected_from_dashboard(self):
        resp = self.client.get(self.dashboard_url)
        self.assertEqual(resp.status_code, 302)
        self.assertIn('/accounts/login', resp.url)  # عدلي المسار لو مختلف

    def test_anonymous_redirected_from_patients(self):
        resp = self.client.get(self.patients_url)
        self.assertEqual(resp.status_code, 302)

    # ---------- Doctor ----------
    def test_doctor_can_access_dashboard(self):
        self.client.login(email=self.doctor_user.email, password=self.password)
        resp = self.client.get(self.dashboard_url)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Dr.')  # شيء مميز بالصفحة

    def test_doctor_can_access_patients_list(self):
        self.client.login(email=self.doctor_user.email, password=self.password)
        resp = self.client.get(self.patients_url)
        self.assertEqual(resp.status_code, 200)

    # ---------- Secretary ----------
    def test_secretary_cannot_access_dashboard(self):
        self.client.login(email=self.secretary_user.email, password=self.password)
        resp = self.client.get(self.dashboard_url)
        # إذا ترجعين 403 (PermissionDenied)
        self.assertEqual(resp.status_code, 403)

    def test_secretary_cannot_access_patients_list(self):
        self.client.login(email=self.secretary_user.email, password=self.password)
        resp = self.client.get(self.patients_url)
        self.assertEqual(resp.status_code, 403)

    # ---------- Random user ----------
    def test_random_user_cannot_access_dashboard(self):
        self.client.login(email=self.random_user.email, password=self.password)
        resp = self.client.get(self.dashboard_url)
        self.assertEqual(resp.status_code, 403)

    def test_random_user_cannot_access_patients_list(self):
        self.client.login(email=self.random_user.email, password=self.password)
        resp = self.client.get(self.patients_url)
        self.assertEqual(resp.status_code, 403)
