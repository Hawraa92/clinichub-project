import os
import shutil
import tempfile

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings

from doctor.models import Doctor
from patient.models import Patient
from medical_archive.models import PatientArchive, ArchiveAttachment

User = get_user_model()


@override_settings(MEDIA_ROOT=tempfile.mkdtemp(prefix="test_media_"))
class AttachmentTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        # تنظيف MEDIA_ROOT المؤقت
        media_root = getattr(cls, "MEDIA_ROOT", None)
        # override_settings يعيّن MEDIA_ROOT فعليًا داخل settings
        try:
            from django.conf import settings
            media_root = settings.MEDIA_ROOT
        except Exception:
            pass

        super().tearDownClass()
        if media_root and os.path.isdir(media_root):
            shutil.rmtree(media_root, ignore_errors=True)

    def _set_role_if_exists(self, user, role_value: str) -> None:
        # حتى ما تعتمد على وجود role أو قبول create_user للـ role
        if hasattr(user, "role"):
            try:
                user.role = role_value
                user.save(update_fields=["role"])
            except Exception:
                user.role = role_value
                user.save()

    def setUp(self):
        # ✅ افصل حساب الدكتور عن حساب المريض
        self.doctor_user = User.objects.create_user(
            email="doc_attach@test.com",
            password="pass",
            username="doc_attach",
        )
        self._set_role_if_exists(self.doctor_user, "doctor")

        self.patient_user = User.objects.create_user(
            email="pat_attach@test.com",
            password="pass",
            username="pat_attach",
        )
        self._set_role_if_exists(self.patient_user, "patient")

        # ✅ إذا عندك signal ينشئ Patient تلقائيًا راح يرجع الموجود
        self.patient, _ = Patient.objects.get_or_create(
            user=self.patient_user,
            defaults={"full_name": "Ali Attachment"},
        )

        self.doctor, _ = Doctor.objects.get_or_create(
            user=self.doctor_user,
            defaults={"full_name": "Dr. Attach", "specialty": "Eye"},
        )

        self.archive = PatientArchive.objects.create(
            patient=self.patient,
            doctor=self.doctor,
            title="Attach Record",
            archive_type="visit",
            status="final",
        )

    def test_upload_multiple_attachments(self):
        file1 = SimpleUploadedFile("a.pdf", b"file_content1", content_type="application/pdf")
        file2 = SimpleUploadedFile("b.jpg", b"file_content2", content_type="image/jpeg")
        ArchiveAttachment.objects.create(archive=self.archive, file=file1)
        ArchiveAttachment.objects.create(archive=self.archive, file=file2)
        self.assertEqual(self.archive.attachments.count(), 2)

    def test_reject_large_file(self):
        big_content = b"a" * (11 * 1024 * 1024)  # 11MB
        big_file = SimpleUploadedFile("big.pdf", big_content, content_type="application/pdf")
        att = ArchiveAttachment(archive=self.archive, file=big_file)
        with self.assertRaises(ValidationError):
            att.full_clean()

    def test_reject_wrong_file_type(self):
        exe_file = SimpleUploadedFile("virus.exe", b"12345", content_type="application/x-msdownload")
        att = ArchiveAttachment(archive=self.archive, file=exe_file)
        with self.assertRaises(ValidationError):
            att.full_clean()

    def test_delete_attachment_removes_file(self):
        file_data = SimpleUploadedFile("c.jpg", b"test", content_type="image/jpeg")
        att = ArchiveAttachment.objects.create(archive=self.archive, file=file_data)

        # قد يختلف حسب storage، بس بالـ FileSystemStorage يكون موجود
        path = getattr(att.file, "path", None)
        self.assertTrue(path and os.path.exists(path))

        att.delete()
        self.assertFalse(os.path.exists(path))

    def test_image_tag_and_is_image(self):
        file_data = SimpleUploadedFile("d.jpg", b"img", content_type="image/jpeg")
        att = ArchiveAttachment.objects.create(archive=self.archive, file=file_data)
        self.assertTrue(att.is_image())
        # ✅ لازم image_tag موجود بالموديل (اللي ضفناه)
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
            description="تحليل دم",
        )
        self.assertEqual(att.description, "تحليل دم")
