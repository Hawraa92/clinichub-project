# medical_archive/test_edge_cases.py

from django.test import TestCase, Client
from django.core.files.uploadedfile import SimpleUploadedFile
from django.contrib.auth import get_user_model
from django.urls import reverse
from patient.models import Patient
from doctor.models import Doctor
from medical_archive.models import PatientArchive, ArchiveAttachment

User = get_user_model()

class EdgeCasesTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email='edge@test.com', password='pass', username='user')
        self.doctor = Doctor.objects.create(user=self.user, full_name='د. استثناء', specialty='اختبار')
        self.patient = Patient.objects.create(user=self.user, full_name='محمد حروف خاصة')
        self.archive = PatientArchive.objects.create(
            patient=self.patient,
            doctor=self.doctor,
            title="سجل تجريبي 🎉 اختبار ملفات",
            archive_type='lab',
            status='final'
        )
        self.client = Client()
        self.client.login(email='edge@test.com', password='pass')

    def test_upload_unicode_filename_attachment(self):
        # رفع ملف اسمه بالعربي أو فيه Unicode
        arabic_filename = "تقرير_نهائي_عربي😊.pdf"
        file_bytes = b"EDGE_TEST"
        attachment = ArchiveAttachment.objects.create(
            archive=self.archive,
            file=SimpleUploadedFile(arabic_filename, file_bytes, content_type="application/pdf"),
            description='ملف عربي'
        )
        # ❌ لا داعي لفحص الاسم العربي في المسار: سيحفظ كـ UUID
        # self.assertIn("تقرير_نهائي_عربي", attachment.file.name)

        # ✔️ جربي التحميل وتحققي من محتوى الملف
        download_url = reverse('medical_archive:download_attachment', args=[attachment.pk])
        response = self.client.get(download_url)
        self.assertEqual(response.status_code, 200)
        actual_bytes = b"".join(response.streaming_content)
        self.assertEqual(actual_bytes, file_bytes)

    def test_delete_archive_deletes_attachments(self):
        # أضف مرفقات
        a1 = ArchiveAttachment.objects.create(
            archive=self.archive,
            file=SimpleUploadedFile("test1.pdf", b"1", content_type="application/pdf")
        )
        a2 = ArchiveAttachment.objects.create(
            archive=self.archive,
            file=SimpleUploadedFile("test2.png", b"2", content_type="image/png")
        )
        # تأكد أن الاثنين موجودين
        self.assertEqual(ArchiveAttachment.objects.filter(archive=self.archive).count(), 2)
        # احذف الأرشيف (cascade)
        self.archive.delete()
        # تأكد أن جميع المرفقات انحذفت معه
        self.assertEqual(ArchiveAttachment.objects.filter(archive_id=self.archive.pk).count(), 0)
