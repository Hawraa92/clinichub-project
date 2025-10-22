from datetime import timedelta
from django.test import TestCase
from django.utils import timezone
from django.contrib.auth import get_user_model

from doctor.models import Doctor
from patient.models import Patient
from appointments.models import Appointment

User = get_user_model()


class AppointmentModelTests(TestCase):
    def setUp(self):
        # مستخدم دكتور
        u_doc = User.objects.create_user(email='doc@example.com', password='pass123', username='doc', role='doctor')
        self.doctor = Doctor.objects.create(user=u_doc)
        # مريض
        self.patient = Patient.objects.create(full_name='Test Patient')

    def future_dt(self, days=1, hour=10, minute=0):
        dt = timezone.localtime(timezone.now()) + timedelta(days=days)
        return dt.replace(hour=hour, minute=minute, second=0, microsecond=0)

    def test_create_valid_appointment(self):
        appt = Appointment.objects.create(
            doctor=self.doctor,
            patient=self.patient,
            scheduled_time=self.future_dt()
        )
        self.assertIsNotNone(appt.pk)
        self.assertGreater(appt.queue_number, 0)

    def test_ordering_by_scheduled_time(self):
        p2 = Patient.objects.create(full_name='Another')
        early = self.future_dt(hour=9)
        late = self.future_dt(hour=11)
        a1 = Appointment.objects.create(doctor=self.doctor, patient=self.patient, scheduled_time=late)
        a2 = Appointment.objects.create(doctor=self.doctor, patient=p2, scheduled_time=early)
        ordered = list(Appointment.objects.order_by('scheduled_time'))
        self.assertEqual(ordered[0].id, a2.id)

    def test_cannot_book_past(self):
        past = timezone.localtime(timezone.now()) - timedelta(hours=2)
        with self.assertRaises(Exception):
            Appointment.objects.create(doctor=self.doctor, patient=self.patient, scheduled_time=past)
