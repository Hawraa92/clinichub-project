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


class EdgeCasesTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="edge@test.com",
            password="pass",
            username="user",
            role="doctor",
            is_approved=True,
        )
        self.doctor = Doctor.objects.create(
            user=self.user,
            full_name="?. ???????",
            specialty="??????",
        )
        self.patient, _ = Patient.objects.update_or_create(
            user=self.user,
            defaults={
                "full_name": "???? ???? ????",
                "doctor": self.doctor,
            },
        )
        self.archive = PatientArchive.objects.create(
            patient=self.patient,
            doctor=self.doctor,
            title="??? ?????? ?? ?????? ?????",
            archive_type="lab",
            status="final",
        )

        grant_archive_permissions(self.user)

        self.client = Client()
        self.client.force_login(self.user)

    def test_upload_unicode_filename_attachment(self):
        file_bytes = b"EDGE_TEST"

        attachment = ArchiveAttachment.objects.create(
            archive=self.archive,
            file=SimpleUploadedFile(
                "?????_?????_??????.pdf",
                file_bytes,
                content_type="application/pdf",
            ),
            description="??? ????",
        )

        response = self.client.get(
            reverse(
                "medical_archive:download_attachment",
                args=[attachment.pk],
            )
        )

        self.assertEqual(
            response.status_code,
            200,
        )
        self.assertEqual(
            b"".join(response.streaming_content),
            file_bytes,
        )

    def test_delete_archive_deletes_attachments(self):
        ArchiveAttachment.objects.create(
            archive=self.archive,
            file=SimpleUploadedFile(
                "test1.pdf",
                b"1",
                content_type="application/pdf",
            ),
        )
        ArchiveAttachment.objects.create(
            archive=self.archive,
            file=SimpleUploadedFile(
                "test2.png",
                b"2",
                content_type="image/png",
            ),
        )

        self.assertEqual(
            ArchiveAttachment.objects.filter(
                archive=self.archive
            ).count(),
            2,
        )

        archive_id = self.archive.pk
        self.archive.delete()

        self.assertEqual(
            ArchiveAttachment.objects.filter(
                archive_id=archive_id
            ).count(),
            0,
        )
