# medical_archive/tests.py

from django.test import TestCase, Client
from django.urls import reverse
from django.core.files.uploadedfile import SimpleUploadedFile
from django.contrib.auth import get_user_model

from patient.models import Patient
from doctor.models import Doctor
from medical_archive.models import PatientArchive, ArchiveAttachment

User = get_user_model()

class MedicalArchiveTests(TestCase):

    def setUp(self):
        # إنشاء مستخدمين لطبيب ومريض
        self.doctor_user = User.objects.create_user(email='doc@test.com', password='pass', username='doc')
        self.patient_user = User.objects.create_user(email='pat@test.com', password='pass', username='pat')
        self.doctor = Doctor.objects.create(user=self.doctor_user, full_name='Dr. Test', specialty='Cardiology')
        self.patient = Patient.objects.create(user=self.patient_user, full_name='Ali Ahmed')

        # تسجيل دخول كدكتور (أو سكرتير إذا تحتاج)
        self.client = Client()
        self.client.login(email='doc@test.com', password='pass')

    def test_create_medical_archive(self):
        url = reverse('medical_archive:create_archive')
        data = {
            'patient': self.patient.id,
            'doctor': self.doctor.id,
            'title': "Routine Checkup",
            'archive_type': 'visit',
            'status': 'final',
            'notes': '',
            'is_critical': False,
            'summary_report': '',
        }
        response = self.client.post(url, data, follow=True)
        self.assertIn(response.status_code, [200, 302])
        self.assertTrue(
            PatientArchive.objects.filter(
                patient=self.patient,
                doctor=self.doctor,
                title="Routine Checkup"
            ).exists()
        )

    def test_medical_archive_detail_view(self):
        # إنشاء سجل أولاً
        archive = PatientArchive.objects.create(
            patient=self.patient,
            doctor=self.doctor,
            title="Test Visit",
            archive_type='visit',
            status='final'
        )
        url = reverse('medical_archive:archive_detail', kwargs={'archive_id': archive.pk})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Test Visit")

    def test_medical_archive_list_view(self):
        PatientArchive.objects.create(
            patient=self.patient,
            doctor=self.doctor,
            title="Visit 1",
            archive_type='visit',
            status='final'
        )
        url = reverse('medical_archive:archive_list')
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Visit 1")

    def test_file_attachment_upload(self):
        file_data = SimpleUploadedFile("test2.jpg", b"file_content", content_type="image/jpeg")
        archive = PatientArchive.objects.create(
            patient=self.patient,
            doctor=self.doctor,
            title="Attachment Test",
            archive_type='visit',
            status='final'
        )
        attachment = ArchiveAttachment.objects.create(
            archive=archive,
            file=file_data,
            description='Test Image'
        )
        # ✅ نستخدم دالة is_image للتأكد أن المرفق صورة
        self.assertTrue(attachment.is_image())

    def test_str_method(self):
        archive = PatientArchive.objects.create(
            patient=self.patient,
            doctor=self.doctor,
            title="String method test",
            archive_type='visit',
            status='final'
        )
        self.assertIn("String method test", str(archive))
