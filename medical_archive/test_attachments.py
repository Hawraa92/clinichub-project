from django.test import TestCase
from django.core.files.uploadedfile import SimpleUploadedFile
from django.contrib.auth import get_user_model
from patient.models import Patient
from doctor.models import Doctor
from medical_archive.models import PatientArchive, ArchiveAttachment

User = get_user_model()

class AttachmentTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email='test@test.com', password='pass', username='user')
        self.doctor = Doctor.objects.create(user=self.user, full_name='Dr. Attach', specialty='Eye')
        self.patient = Patient.objects.create(user=self.user, full_name='Ali Attachment')
        self.archive = PatientArchive.objects.create(
            patient=self.patient,
            doctor=self.doctor,
            title="Attach Record",
            archive_type='visit',
            status='final'
        )

    def test_upload_multiple_attachments(self):
        # رفع ملفين لنفس الأرشيف
        file1 = SimpleUploadedFile("a.pdf", b"file_content1", content_type="application/pdf")
        file2 = SimpleUploadedFile("b.jpg", b"file_content2", content_type="image/jpeg")
        att1 = ArchiveAttachment.objects.create(archive=self.archive, file=file1)
        att2 = ArchiveAttachment.objects.create(archive=self.archive, file=file2)
        self.assertEqual(self.archive.attachments.count(), 2)

    def test_reject_large_file(self):
        # رفع ملف يتجاوز الحجم المسموح
        big_content = b"a" * (11 * 1024 * 1024)  # 11MB
        big_file = SimpleUploadedFile("big.pdf", big_content, content_type="application/pdf")
        from django.core.exceptions import ValidationError
        with self.assertRaises(ValidationError):
            att = ArchiveAttachment(
                archive=self.archive,
                file=big_file
            )
            att.full_clean()

    def test_reject_wrong_file_type(self):
        # رفع ملف غير مسموح
        exe_file = SimpleUploadedFile("virus.exe", b"12345", content_type="application/x-msdownload")
        from django.core.exceptions import ValidationError
        with self.assertRaises(ValidationError):
            att = ArchiveAttachment(
                archive=self.archive,
                file=exe_file
            )
            att.full_clean()

    def test_delete_attachment_removes_file(self):
        # التأكد من حذف الملف من التخزين عند حذف المرفق
        file_data = SimpleUploadedFile("c.jpg", b"test", content_type="image/jpeg")
        att = ArchiveAttachment.objects.create(archive=self.archive, file=file_data)
        path = att.file.path
        att.delete()
        import os
        self.assertFalse(os.path.exists(path))

    def test_image_tag_and_is_image(self):
        file_data = SimpleUploadedFile("d.jpg", b"img", content_type="image/jpeg")
        att = ArchiveAttachment.objects.create(archive=self.archive, file=file_data)
        self.assertTrue(att.is_image())
        self.assertIn("<img", att.image_tag())

    def test_pdf_not_image(self):
        file_data = SimpleUploadedFile("e.pdf", b"pdf", content_type="application/pdf")
        att = ArchiveAttachment.objects.create(archive=self.archive, file=file_data)
        self.assertFalse(att.is_image())
        self.assertTrue(att.is_pdf())
        self.assertEqual(att.image_tag(), "-")

    def test_description_is_saved(self):
        file_data = SimpleUploadedFile("f.png", b"img", content_type="image/png")
        att = ArchiveAttachment.objects.create(
            archive=self.archive,
            file=file_data,
            description="تحليل دم"
        )
        self.assertEqual(att.description, "تحليل دم")
