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


class MedicalArchiveTests(TestCase):
    def setUp(self):
        self.doctor_user = User.objects.create_user(
            email="doc@test.com",
            password="pass",
            username="doc",
            role="doctor",
            is_approved=True,
        )
        self.patient_user = User.objects.create_user(
            email="pat@test.com",
            password="pass",
            username="pat",
            role="patient",
            is_approved=True,
        )

        self.doctor = Doctor.objects.create(
            user=self.doctor_user,
            full_name="Dr. Test",
            specialty="Cardiology",
        )
        self.patient, _ = Patient.objects.update_or_create(
            user=self.patient_user,
            defaults={
                "full_name": "Ali Ahmed",
                "doctor": self.doctor,
            },
        )

        grant_archive_permissions(
            self.doctor_user,
            allow_create=True,
        )

        self.client = Client()
        self.client.force_login(self.doctor_user)

    def test_create_medical_archive(self):
        url = reverse(
            "medical_archive:create_archive"
        )
        data = {
            "patient": self.patient.id,
            "doctor": self.doctor.id,
            "title": ["Routine Checkup", ""],
            "archive_type": "visit",
            "status": "final",
            "notes": "",
            "is_critical": False,
            "summary_report": "",
        }

        response = self.client.post(
            url,
            data,
            follow=True,
        )

        self.assertEqual(
            response.status_code,
            200,
        )
        self.assertTrue(
            PatientArchive.objects.filter(
                patient=self.patient,
                doctor=self.doctor,
                title="Routine Checkup",
            ).exists()
        )

    def test_medical_archive_detail_view(self):
        archive = PatientArchive.objects.create(
            patient=self.patient,
            doctor=self.doctor,
            title="Test Visit",
            archive_type="visit",
            status="final",
        )

        response = self.client.get(
            reverse(
                "medical_archive:archive_detail",
                kwargs={"archive_id": archive.pk},
            )
        )

        self.assertEqual(
            response.status_code,
            200,
        )
        self.assertContains(
            response,
            "Test Visit",
        )

    def test_medical_archive_list_view(self):
        PatientArchive.objects.create(
            patient=self.patient,
            doctor=self.doctor,
            title="Visit 1",
            archive_type="visit",
            status="final",
        )

        response = self.client.get(
            reverse(
                "medical_archive:archive_list"
            )
        )

        self.assertEqual(
            response.status_code,
            200,
        )
        self.assertContains(
            response,
            "Visit 1",
        )

    def test_file_attachment_upload(self):
        archive = PatientArchive.objects.create(
            patient=self.patient,
            doctor=self.doctor,
            title="Attachment Test",
            archive_type="visit",
            status="final",
        )

        attachment = ArchiveAttachment.objects.create(
            archive=archive,
            file=SimpleUploadedFile(
                "test2.jpg",
                b"file_content",
                content_type="image/jpeg",
            ),
            description="Test Image",
        )

        self.assertTrue(
            attachment.is_image()
        )

    def test_str_method(self):
        archive = PatientArchive.objects.create(
            patient=self.patient,
            doctor=self.doctor,
            title="String method test",
            archive_type="visit",
            status="final",
        )

        self.assertIn(
            "String method test",
            str(archive),
        )
