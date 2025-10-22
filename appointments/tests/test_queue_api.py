from datetime import timedelta
from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone
from django.contrib.auth import get_user_model

from doctor.models import Doctor
from patient.models import Patient
from appointments.models import Appointment, AppointmentStatus

User = get_user_model()


class QueueAPITests(TestCase):
    def setUp(self):
        self.client = Client()
        # سكرتيرة
        self.sec_user = User.objects.create_user(
            email='secq@example.com', password='pass123', username='secq', role='secretary'
        )
        # دكتور + مريض
        doc_user = User.objects.create_user(
            email='qdoc@example.com', password='pass123', username='qdoc', role='doctor'
        )
        self.doctor = Doctor.objects.create(user=doc_user)
        self.patient = Patient.objects.create(full_name='Queue Patient')

    def login_sec(self):
        self.client.login(email='secq@example.com', password='pass123')

    def today_dt(self, hour=9):
        base = timezone.localtime(timezone.now())
        return base.replace(hour=hour, minute=0, second=0, microsecond=0)

    def test_queue_number_api_empty(self):
        self.login_sec()
        url = reverse('appointments:queue_number_api')
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertIn('queues', resp.json())

    def test_queue_number_api_with_appointment(self):
        self.login_sec()
        Appointment.objects.create(
            doctor=self.doctor,
            patient=self.patient,
            scheduled_time=self.today_dt(),
            status=AppointmentStatus.PENDING
        )
        url = reverse('appointments:queue_number_api')
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data['queues'])
