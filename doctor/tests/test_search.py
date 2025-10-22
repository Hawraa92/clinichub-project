# doctor/tests/test_search.py
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

class DoctorAdvancedSearchTest(TestCase):
    def setUp(self):
        self.doctor_user = User.objects.create_user(email="dr@clinic.com", password=PASSWORD, role='doctor')
        self.doctor = Doctor.objects.create(user=self.doctor_user, full_name="Dr. Search")
        self.client.login(email="dr@clinic.com", password=PASSWORD)
        self.now = timezone.now()
        # أنشئ مرضى بتسميات مختلفة
        self.patient_full = Patient.objects.create(full_name="Sarah Johnson")
        self.patient_partial = Patient.objects.create(full_name="Sara K.")
        self.patient_other = Patient.objects.create(full_name="Michael Smith")
        # اربط المرضى بمواعيد (كلها مستقبلية)
        Appointment.objects.create(
            patient=self.patient_full, 
            doctor=self.doctor, 
            scheduled_time=self.now + timedelta(days=1)
        )
        Appointment.objects.create(
            patient=self.patient_partial, 
            doctor=self.doctor, 
            scheduled_time=self.now + timedelta(days=2)
        )
        Appointment.objects.create(
            patient=self.patient_other, 
            doctor=self.doctor, 
            scheduled_time=self.now + timedelta(days=4)
        )

    def test_search_by_full_name(self):
        url = reverse('doctor:patient_search') + '?q=Sarah Johnson'
        resp = self.client.get(url)
        self.assertContains(resp, "Sarah Johnson")
        self.assertNotContains(resp, "Michael Smith")
    
    def test_search_by_partial_name(self):
        url = reverse('doctor:patient_search') + '?q=Sara'
        resp = self.client.get(url)
        self.assertContains(resp, "Sarah Johnson")
        self.assertContains(resp, "Sara K.")
        self.assertNotContains(resp, "Michael Smith")

    def test_search_by_id(self):
        url = reverse('doctor:patient_search') + f'?q={self.patient_other.id}'
        resp = self.client.get(url)
        self.assertContains(resp, "Michael Smith")

    # def test_search_by_date_range(self):
    #     # معلقة حتى تطبق فلترة التاريخ فعلياً في view
    #     date = (self.now + timedelta(days=2)).date().strftime("%Y-%m-%d")
    #     url = reverse('doctor:patient_search') + f'?date_from={date}&date_to={date}'
    #     resp = self.client.get(url)
    #     self.assertContains(resp, "Sara K.")  # فقط اللي عنده موعد بهذا اليوم
