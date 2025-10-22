# doctor/tests/test_templates.py
from django.test import TestCase
from django.urls import reverse
from django.contrib.auth import get_user_model
from doctor.models import Doctor
from medical_archive.models import PatientArchive
from prescription.models import Prescription
from patient.models import Patient

User = get_user_model()


def create_user(email, password='pass1234', role='patient', **kwargs):
    return User.objects.create_user(email=email, password=password, role=role, **kwargs)

def create_doctor_user(email='doc@example.com'):
    user = create_user(email=email, role='doctor')
    Doctor.objects.create(user=user, full_name='Dr. Test')
    return user


class DoctorTemplateTests(TestCase):
    def setUp(self):
        self.dashboard_url = reverse('doctor:dashboard')
        self.doctor_user = create_doctor_user()
        self.secretary_user = create_user('sec@example.com', role='secretary')
        self.password = 'pass1234'

    def test_dashboard_uses_correct_template(self):
        self.client.login(email=self.doctor_user.email, password=self.password)
        resp = self.client.get(self.dashboard_url)
        self.assertEqual(resp.status_code, 200)
        self.assertTemplateUsed(resp, 'doctor/doctor_dashboard.html')

    def test_doctor_sees_expected_buttons(self):
        self.client.login(email=self.doctor_user.email, password=self.password)
        resp = self.client.get(self.dashboard_url)
        # عدلي النصوص حسب الموجود
        self.assertContains(resp, 'Prescriptions')
        self.assertContains(resp, 'Patients')
        self.assertNotContains(resp, 'Queue')  # إذا فعلاً مخفي

    def test_secretary_cannot_see_doctor_dashboard(self):
        self.client.login(email=self.secretary_user.email, password=self.password)
        resp = self.client.get(self.dashboard_url)
        # إذا تعيدون 403:
        self.assertEqual(resp.status_code, 403)

    def test_context_data_present(self):
        self.client.login(email=self.doctor_user.email, password=self.password)
        resp = self.client.get(self.dashboard_url)
        # تأكد من وجود stats (أو أي مفتاح ثاني أنتِ تستخدمينه)
        self.assertIn('stats', resp.context)
        # لو أضفنا prescription_count فوق
        self.assertIn('prescription_count', resp.context['stats'])
