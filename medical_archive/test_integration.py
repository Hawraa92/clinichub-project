from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase

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


class ArchiveIntegrationTest(TestCase):
    def test_full_workflow(self):
        user = User.objects.create_user(
            email="int@test.com",
            password="pass",
            username="user",
            role="doctor",
            is_approved=True,
        )
        doctor = Doctor.objects.create(
            user=user,
            full_name="Dr. Integrate",
            specialty="Gen",
        )
        patient, _ = Patient.objects.update_or_create(
            user=user,
            defaults={
                "full_name": "Ali Integrate",
                "doctor": doctor,
            },
        )

        grant_archive_permissions(user)

        client = Client()
        client.force_login(user)

        archive = PatientArchive.objects.create(
            patient=patient,
            doctor=doctor,
            title="Integration Archive",
            archive_type="visit",
            status="final",
        )
        ArchiveAttachment.objects.create(
            archive=archive,
            file=SimpleUploadedFile(
                "integrate.pdf",
                b"123456",
                content_type="application/pdf",
            ),
            description="Test",
        )

        response = client.get(
            "/archive/",
            {"search": "Integration"},
        )

        self.assertEqual(
            response.status_code,
            200,
        )
        self.assertContains(
            response,
            "Integration Archive",
        )

        archive.delete()

        self.assertEqual(
            PatientArchive.objects.count(),
            0,
        )
        self.assertEqual(
            ArchiveAttachment.objects.count(),
            0,
        )
