from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase
from django.urls import reverse

from doctor.models import Doctor
from medical_archive.models import (
    ArchiveAttachment,
    PatientArchive,
)
from medical_archive.test_support import (
    grant_archive_permissions,
)
from patient.models import Patient


User = get_user_model()


class DownloadPreviewTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="test@download.com",
            password="pass",
            username="user",
            role="doctor",
            is_approved=True,
        )
        self.doctor = Doctor.objects.create(
            user=self.user,
            full_name="Dr. Preview",
            specialty="Lab",
        )
        self.patient, _ = Patient.objects.update_or_create(
            user=self.user,
            defaults={
                "full_name": "Ali Preview",
                "doctor": self.doctor,
            },
        )
        self.archive = PatientArchive.objects.create(
            patient=self.patient,
            doctor=self.doctor,
            title="Preview Record",
            archive_type="lab",
            status="final",
        )

        self.img_bytes = (
            b"\x89PNG\r\n\x1a\nimgcontent"
        )
        self.pdf_bytes = (
            b"%PDF-1.4 pdfcontent"
        )

        self.img_attachment = (
            ArchiveAttachment.objects.create(
                archive=self.archive,
                file=SimpleUploadedFile(
                    "xray.png",
                    self.img_bytes,
                    content_type="image/png",
                ),
                description="X-ray",
            )
        )
        self.pdf_attachment = (
            ArchiveAttachment.objects.create(
                archive=self.archive,
                file=SimpleUploadedFile(
                    "report.pdf",
                    self.pdf_bytes,
                    content_type="application/pdf",
                ),
                description="Lab Report",
            )
        )

        grant_archive_permissions(self.user)

        self.client = Client()
        self.client.force_login(self.user)

    def test_download_attachment_and_compare_bytes(self):
        image_response = self.client.get(
            reverse(
                "medical_archive:download_attachment",
                args=[self.img_attachment.pk],
            )
        )

        self.assertEqual(
            image_response.status_code,
            200,
        )
        self.assertEqual(
            b"".join(
                image_response.streaming_content
            ),
            self.img_bytes,
        )

        pdf_response = self.client.get(
            reverse(
                "medical_archive:download_attachment",
                args=[self.pdf_attachment.pk],
            )
        )

        self.assertEqual(
            pdf_response.status_code,
            200,
        )
        self.assertEqual(
            b"".join(
                pdf_response.streaming_content
            ),
            self.pdf_bytes,
        )

    def test_image_and_pdf_preview(self):
        self.assertTrue(
            self.img_attachment.is_image()
        )
        self.assertIn(
            "<img",
            str(
                self.img_attachment.preview_html()
            ),
        )

        self.assertTrue(
            self.pdf_attachment.is_pdf()
        )
        self.assertFalse(
            self.pdf_attachment.is_image()
        )
        self.assertEqual(
            self.pdf_attachment.preview_html(),
            "-",
        )
