from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth import get_user_model
from django.utils import timezone
from datetime import timedelta

from doctor.models import Doctor
from patient.models import Patient

User = get_user_model()

class DoctorViewsTests(TestCase):
    def setUp(self):
        self.client = Client()
        # إنشاء حساب طبيب وحساب مريض للاختبار
        self.doctor_user = User.objects.create_user(
            email='doc@example.com',
            username='doc',
            password='pwd',
            role='doctor',
        )
        self.doctor = Doctor.objects.create(
            user=self.doctor_user,
            specialty='Dentist'
        )
        self.patient = Patient.objects.create(full_name='John Doe')
        # حجز موعد مؤجّل قليلًا لتجنّب خطأ الحجز في الماضي
        from appointments.models import Appointment
        Appointment.objects.create(
            doctor=self.doctor,
            patient=self.patient,
            scheduled_time=timezone.now() + timedelta(minutes=1),
        )
        # مستخدم مريض لاختبار صلاحيات الوصول
        self.patient_user = User.objects.create_user(
            email='patient@example.com',
            username='patient',
            password='pwd',
            role='patient',
        )

    def test_dashboard_requires_login(self):
        resp = self.client.get(reverse('doctor:dashboard'))
        self.assertRedirects(
            resp,
            f'/accounts/login/?next={reverse("doctor:dashboard")}')

    def test_dashboard_forbidden_for_non_doctor(self):
        # تسجيل دخول مريض (ليس طبيبًا)
        self.client.force_login(self.patient_user)
        resp = self.client.get(reverse('doctor:dashboard'))
        self.assertEqual(resp.status_code, 403)

    def test_dashboard_displays_stats(self):
        # تسجيل دخول الطبيب
        self.client.force_login(self.doctor_user)
        resp = self.client.get(reverse('doctor:dashboard'))
        self.assertEqual(resp.status_code, 200)
        # التأكد من وجود إحصاءات بالـ context
        self.assertIn('stats', resp.context)
        stats = resp.context['stats']
        self.assertEqual(stats['total_archives'], 0)
        self.assertEqual(stats['patients_today'], 1)

    def test_patients_list(self):
        self.client.force_login(self.doctor_user)
        resp = self.client.get(reverse('doctor:patients_list'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'John Doe')  # التأكد من عرض اسم المريض

    def test_patient_search(self):
        self.client.force_login(self.doctor_user)
        url = reverse('doctor:patient_search') + '?q=John'
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'John Doe')  # التأكد من عمل البحث بشكل صحيح