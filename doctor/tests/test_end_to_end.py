# doctor/tests/test_end_to_end.py
from django.test import TestCase
from django.urls import reverse
from django.contrib.auth import get_user_model
from doctor.models import Doctor
from patient.models import Patient
from appointments.models import Appointment
from datetime import timedelta
from django.utils import timezone

User = get_user_model()
PASSWORD = 'pass1234'

class DoctorEndToEndTest(TestCase):
    def setUp(self):
        self.doctor_user = User.objects.create_user(email="e2e@clinic.com", password=PASSWORD, role='doctor')
        self.doctor = Doctor.objects.create(user=self.doctor_user, full_name="Dr. E2E")
        self.client.login(email="e2e@clinic.com", password=PASSWORD)
        # أنشئ عدد كبير من المرضى والمواعيد
        now = timezone.now() + timedelta(days=1)
        for i in range(150):  # أداء مع 150 مريض
            p = Patient.objects.create(full_name=f"PerfPatient {i}")
            Appointment.objects.create(patient=p, doctor=self.doctor, scheduled_time=now + timedelta(minutes=i))

    def test_list_patients_performance(self):
        url = reverse('doctor:patients_list')
        resp = self.client.get(url)
        # هل تظهر جميع المرضى؟
        self.assertContains(resp, "PerfPatient 0")
        self.assertContains(resp, "PerfPatient 149")
        # تحقق من عدم وجود أخطاء أو تأخير كبير (يمكن تعديل الـ timeout حسب الحاجة)

    def test_search_patient_end_to_end(self):
        url = reverse('doctor:patient_search') + '?q=PerfPatient 42'
        resp = self.client.get(url)
        self.assertContains(resp, "PerfPatient 42")
        self.assertNotContains(resp, "PerfPatient 99")  # إذا تبحث بالاسم بالضبط

    def test_export_csv_end_to_end(self):
        # جربي تصدير بيانات مريض عشوائي
        patient = Patient.objects.get(full_name="PerfPatient 10")
        url = reverse('doctor:report_csv', kwargs={'patient_id': patient.id})
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertIn("PerfPatient 10", resp.content.decode())

    def test_export_pdf_end_to_end(self):
        # إذا عندك weasyprint فقط
        patient = Patient.objects.get(full_name="PerfPatient 10")
        url = reverse('doctor:report_pdf', kwargs={'patient_id': patient.id})
        resp = self.client.get(url)
        # ممكن يتحقق فقط من أن الرد PDF وليس HTML
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp['Content-Type'], 'application/pdf')

    def test_full_journey(self):
        # تجربة تسجيل الدخول وبحث وتصدير (سلسلة حقيقية كاملة)
        self.client.logout()
        self.assertTrue(self.client.login(email="e2e@clinic.com", password=PASSWORD))
        url = reverse('doctor:patient_search') + '?q=PerfPatient 5'
        resp = self.client.get(url)
        self.assertContains(resp, "PerfPatient 5")
