# medical_archive/test_search_filter.py

from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth import get_user_model
from patient.models import Patient
from doctor.models import Doctor
from medical_archive.models import PatientArchive
from datetime import timedelta
from django.utils import timezone

User = get_user_model()

class ArchiveSearchAndFilterTests(TestCase):
    def setUp(self):
        # مستخدم وطبيب ومريض
        self.user = User.objects.create_user(email='test@test.com', password='pass', username='pat')
        self.doctor_user = User.objects.create_user(email='doc@test.com', password='pass', username='doc')
        self.doctor = Doctor.objects.create(user=self.doctor_user, full_name='Dr. Omar', specialty='Heart')
        self.patient = Patient.objects.create(user=self.user, full_name='Ali Search')
        self.client = Client()
        self.client.login(email='test@test.com', password='pass')

        # أرشيفات متنوعة
        today = timezone.now().date()
        self.archive1 = PatientArchive.objects.create(
            patient=self.patient,
            doctor=self.doctor,
            title="Diabetes Lab",
            archive_type='lab',
            status='final',
            created_at=today - timedelta(days=10)
        )
        self.archive2 = PatientArchive.objects.create(
            patient=self.patient,
            doctor=self.doctor,
            title="Chest Scan Result",
            archive_type='scan',
            status='final',
            created_at=today - timedelta(days=5)
        )
        self.archive3 = PatientArchive.objects.create(
            patient=self.patient,
            doctor=self.doctor,
            title="Visit for Fever",
            archive_type='visit',
            status='final',
            created_at=today
        )

    def test_search_by_title(self):
        url = reverse('medical_archive:archive_list')
        response = self.client.get(url, {'search': 'Diabetes'})
        self.assertContains(response, "Diabetes Lab")
        self.assertNotContains(response, "Chest Scan Result")
        self.assertNotContains(response, "Visit for Fever")

    def test_filter_by_type(self):
        url = reverse('medical_archive:archive_list')
        response = self.client.get(url, {'type': 'scan'})
        self.assertContains(response, "Chest Scan Result")
        self.assertNotContains(response, "Diabetes Lab")
        self.assertNotContains(response, "Visit for Fever")

    def test_filter_by_date_range(self):
        url = reverse('medical_archive:archive_list')
        # يفترض فقط تظهر أرشيفات من 6 أيام إلى اليوم
        response = self.client.get(url, {'start_date': (timezone.now().date() - timedelta(days=6)).isoformat()})
        self.assertContains(response, "Chest Scan Result")
        self.assertContains(response, "Visit for Fever")
        self.assertNotContains(response, "Diabetes Lab")

        # فلترة فقط اليوم الحالي
        response2 = self.client.get(url, {
            'start_date': timezone.now().date().isoformat(),
            'end_date': timezone.now().date().isoformat()
        })
        self.assertContains(response2, "Visit for Fever")
        self.assertNotContains(response2, "Diabetes Lab")
        self.assertNotContains(response2, "Chest Scan Result")
