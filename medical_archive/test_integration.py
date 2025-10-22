# medical_archive/test_integration.py

from django.test import TestCase, Client
from django.core.files.uploadedfile import SimpleUploadedFile
from django.contrib.auth import get_user_model
from patient.models import Patient
from doctor.models import Doctor
from medical_archive.models import PatientArchive, ArchiveAttachment

User = get_user_model()

class ArchiveIntegrationTest(TestCase):
    def test_full_workflow(self):
        # 1. تسجيل مستخدم وإنشاء دكتور ومريض
        user = User.objects.create_user(email='int@test.com', password='pass', username='user')
        doctor = Doctor.objects.create(user=user, full_name='Dr. Integrate', specialty='Gen')
        patient = Patient.objects.create(user=user, full_name='Ali Integrate')
        client = Client()
        client.login(email='int@test.com', password='pass')

        # 2. أرشفة سجل مع مرفق
        archive = PatientArchive.objects.create(
            patient=patient,
            doctor=doctor,
            title="Integration Archive",
            archive_type='visit',
            status='final'
        )
        file_data = SimpleUploadedFile("integrate.pdf", b"123456", content_type="application/pdf")
        attachment = ArchiveAttachment.objects.create(
            archive=archive, file=file_data, description="Test"
        )

        # 3. البحث عن السجل
        response = client.get('/archive/?search=Integration')
        assert response.status_code == 200

        # 4. حذف السجل
        archive.delete()
        self.assertEqual(PatientArchive.objects.count(), 0)
        self.assertEqual(ArchiveAttachment.objects.count(), 0)
