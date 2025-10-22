from django.test import TestCase
from django.urls import reverse
from accounts.models import User
from doctor.models import Doctor
from patient.models import Patient
from appointments.models import Appointment
from django.utils import timezone
from datetime import timedelta

class DoctorPerformanceTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email='docperf@test.com',
            password='123456',
            role='doctor'
        )
        self.doctor = Doctor.objects.create(user=self.user, full_name='Perf Dr')

        logged_in = self.client.login(email='docperf@test.com', password='123456')
        assert logged_in, "❌ لم يتم تسجيل الدخول!"

        # أنشئ 1000 مريض + لكل واحد موعد في دقيقة مختلفة
        base_time = timezone.now() + timedelta(days=1)
        for i in range(1000):
            patient = Patient.objects.create(full_name=f'PerfPatient {i}')
            Appointment.objects.create(
                patient=patient,
                doctor=self.doctor,
                scheduled_time=base_time + timedelta(minutes=i)
            )

    def test_patients_list_performance(self):
        url = reverse('doctor:patients_list')
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "PerfPatient 999")
