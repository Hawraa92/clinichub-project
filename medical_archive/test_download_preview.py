# medical_archive/test_download_preview.py

from django.test import TestCase, Client
from django.core.files.uploadedfile import SimpleUploadedFile
from django.contrib.auth import get_user_model
from django.urls import reverse
from patient.models import Patient
from doctor.models import Doctor
from medical_archive.models import PatientArchive, ArchiveAttachment

User = get_user_model()

class DownloadPreviewTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email='test@download.com', password='pass', username='user')
        self.doctor = Doctor.objects.create(user=self.user, full_name='Dr. Preview', specialty='Lab')
        self.patient = Patient.objects.create(user=self.user, full_name='Ali Preview')
        self.archive = PatientArchive.objects.create(
            patient=self.patient,
            doctor=self.doctor,
            title="Preview Record",
            archive_type='lab',
            status='final'
        )
        # رفع صورة و PDF
        self.img_bytes = b'\x89PNG\r\n\x1a\nimgcontent'
        self.pdf_bytes = b'%PDF-1.4 pdfcontent'
        self.img_attachment = ArchiveAttachment.objects.create(
            archive=self.archive,
            file=SimpleUploadedFile("xray.png", self.img_bytes, content_type="image/png"),
            description='X-ray'
        )
        self.pdf_attachment = ArchiveAttachment.objects.create(
            archive=self.archive,
            file=SimpleUploadedFile("report.pdf", self.pdf_bytes, content_type="application/pdf"),
            description='Lab Report'
        )
        self.client = Client()
        self.client.login(email='test@download.com', password='pass')

    def test_download_attachment_and_compare_bytes(self):
        # تحميل ملف الصورة عبر view التحميل المحمي وتطابق البايتات
        file_url = reverse('medical_archive:download_attachment', args=[self.img_attachment.pk])
        response = self.client.get(file_url)
        self.assertEqual(response.status_code, 200)
        actual_img_bytes = b"".join(response.streaming_content)
        self.assertEqual(actual_img_bytes, self.img_bytes)

        # تحميل ملف PDF عبر view التحميل المحمي وتطابق البايتات
        pdf_url = reverse('medical_archive:download_attachment', args=[self.pdf_attachment.pk])
        response2 = self.client.get(pdf_url)
        self.assertEqual(response2.status_code, 200)
        actual_pdf_bytes = b"".join(response2.streaming_content)
        self.assertEqual(actual_pdf_bytes, self.pdf_bytes)

    def test_image_and_pdf_preview(self):
        # تأكدي أن image_tag تعرض img
        self.assertTrue(self.img_attachment.is_image())
        self.assertIn("<img", self.img_attachment.image_tag())

        # تأكدي أن PDF لا يعرض img (يعرض "-")
        self.assertTrue(self.pdf_attachment.is_pdf())
        self.assertFalse(self.pdf_attachment.is_image())
        self.assertEqual(self.pdf_attachment.image_tag(), "-")
