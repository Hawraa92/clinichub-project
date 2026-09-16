from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase

from doctor.models import Doctor
from medical_archive.models import ArchiveAttachment, PatientArchive
from patient.models import Patient

User = get_user_model()


class AttachmentTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="test@test.com",
            password="pass",
            username="user",
        )
        self.doctor = Doctor.objects.create(
            user=self.user,
            full_name="Dr. Attach",
            specialty="Eye",
        )
        self.patient, _ = Patient.objects.update_or_create(
            user=self.user,
            defaults={"full_name": "Ali Attachment"},
        )
        self.archive = PatientArchive.objects.create(
            patient=self.patient,
            doctor=self.doctor,
            title="Attach Record",
            archive_type="visit",
            status="final",
        )

    def test_upload_multiple_attachments(self):
        file1 = SimpleUploadedFile(
            "a.pdf",
            b"file_content1",
            content_type="application/pdf",
        )
        file2 = SimpleUploadedFile(
            "b.jpg",
            b"file_content2",
            content_type="image/jpeg",
        )

        ArchiveAttachment.objects.create(
            archive=self.archive,
            file=file1,
        )
        ArchiveAttachment.objects.create(
            archive=self.archive,
            file=file2,
        )

        self.assertEqual(self.archive.attachments.count(), 2)

    def test_reject_large_file(self):
        from django.core.exceptions import ValidationError

        big_content = b"a" * (11 * 1024 * 1024)
        big_file = SimpleUploadedFile(
            "big.pdf",
            big_content,
            content_type="application/pdf",
        )

        with self.assertRaises(ValidationError):
            attachment = ArchiveAttachment(
                archive=self.archive,
                file=big_file,
            )
            attachment.full_clean()

    def test_reject_wrong_file_type(self):
        from django.core.exceptions import ValidationError

        executable = SimpleUploadedFile(
            "virus.exe",
            b"12345",
            content_type="application/x-msdownload",
        )

        with self.assertRaises(ValidationError):
            attachment = ArchiveAttachment(
                archive=self.archive,
                file=executable,
            )
            attachment.full_clean()

    def test_delete_attachment_removes_file(self):
        import os

        file_data = SimpleUploadedFile(
            "c.jpg",
            b"test",
            content_type="image/jpeg",
        )
        attachment = ArchiveAttachment.objects.create(
            archive=self.archive,
            file=file_data,
        )
        path = attachment.file.path

        attachment.delete()

        self.assertFalse(os.path.exists(path))

    def test_preview_html_and_is_image(self):
        file_data = SimpleUploadedFile(
            "d.jpg",
            b"img",
            content_type="image/jpeg",
        )
        attachment = ArchiveAttachment.objects.create(
            archive=self.archive,
            file=file_data,
        )

        self.assertTrue(attachment.is_image())
        self.assertIn("<img", str(attachment.preview_html()))

    def test_pdf_not_image(self):
        file_data = SimpleUploadedFile(
            "e.pdf",
            b"pdf",
            content_type="application/pdf",
        )
        attachment = ArchiveAttachment.objects.create(
            archive=self.archive,
            file=file_data,
        )

        self.assertFalse(attachment.is_image())
        self.assertTrue(attachment.is_pdf())
        self.assertEqual(attachment.preview_html(), "-")

    def test_description_is_saved(self):
        file_data = SimpleUploadedFile(
            "f.png",
            b"img",
            content_type="image/png",
        )
        attachment = ArchiveAttachment.objects.create(
            archive=self.archive,
            file=file_data,
            description="تحليل دم",
        )

        self.assertEqual(attachment.description, "تحليل دم")
