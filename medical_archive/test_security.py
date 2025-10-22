# medical_archive/test_security.py

from django.test import TestCase, Client
from django.core.files.uploadedfile import SimpleUploadedFile
from django.contrib.auth import get_user_model
from django.urls import reverse
from patient.models import Patient
from doctor.models import Doctor
from medical_archive.models import PatientArchive, ArchiveAttachment

User = get_user_model()

class SecurityTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email='test@security.com', password='pass', username='user')
        self.doctor = Doctor.objects.create(user=self.user, full_name='Dr. Secure', specialty='Test')
        self.patient = Patient.objects.create(user=self.user, full_name="Ali Secure")
        self.archive = PatientArchive.objects.create(
            patient=self.patient,
            doctor=self.doctor,
            title="Secure Test Archive",
            archive_type="visit",
            status="final"
        )
        self.client = Client()
        self.client.login(email='test@security.com', password='pass')

    def test_upload_invalid_file_content(self):
        # رفع ملف بامتداد صحيح لكن محتوى غير صحيح
        invalid_file = SimpleUploadedFile("test_image.jpg", b"This is a text file pretending to be an image.", content_type="image/jpeg")

        response = self.client.post(f'/medical_archive/{self.archive.id}/attachments/', {
            'file': invalid_file,
            'description': 'Invalid file content test'
        })

        # إذا كان الملف غير صالح، يجب أن يتلقى المستخدم استجابة 404
        self.assertEqual(response.status_code, 404)

    def test_upload_script_file(self):
        # محاولة رفع ملف يحتوي على سكريبت JavaScript (مثلاً ملف .jpg يحتوي على سكريبت)
        malicious_file = SimpleUploadedFile("malicious_image.jpg", b"<script>alert('Hacked!');</script>", content_type="image/jpeg")

        response = self.client.post(f'/medical_archive/{self.archive.id}/attachments/', {
            'file': malicious_file,
            'description': 'Script injection test'
        })

        # إذا كان الملف يحتوي على سكريبت، يجب أن يتلقى المستخدم استجابة 404
        self.assertEqual(response.status_code, 404)

    def test_url_injection(self):
        # محاولة حقن URL في الطلب
        malicious_url = "/medical_archive/1/edit/?id=<script>alert('Hacked')</script>"

        response = self.client.get(malicious_url)

        # إذا كان هناك محاولة حقن URL، يجب أن يتم رفض هذه المحاولة
        self.assertEqual(response.status_code, 404)
