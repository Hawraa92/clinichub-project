from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from doctor.models import Doctor
from medical_archive.models import PatientArchive
from medical_archive.test_support import (
    grant_archive_permissions,
)
from patient.models import Patient


User = get_user_model()


class ArchiveSearchAndFilterTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="test@test.com",
            password="pass",
            username="pat",
            role="patient",
            is_approved=True,
        )
        self.doctor_user = User.objects.create_user(
            email="doc@test.com",
            password="pass",
            username="doc",
            role="doctor",
            is_approved=True,
        )
        self.doctor = Doctor.objects.create(
            user=self.doctor_user,
            full_name="Dr. Omar",
            specialty="Heart",
        )
        self.patient, _ = Patient.objects.update_or_create(
            user=self.user,
            defaults={
                "full_name": "Ali Search",
                "doctor": self.doctor,
            },
        )

        grant_archive_permissions(self.user)

        self.client = Client()
        self.client.force_login(self.user)

        now = timezone.now()

        self.archive1 = PatientArchive.objects.create(
            patient=self.patient,
            doctor=self.doctor,
            title="Diabetes Lab",
            archive_type="lab",
            status="final",
        )
        self.archive2 = PatientArchive.objects.create(
            patient=self.patient,
            doctor=self.doctor,
            title="Chest Scan Result",
            archive_type="scan",
            status="final",
        )
        self.archive3 = PatientArchive.objects.create(
            patient=self.patient,
            doctor=self.doctor,
            title="Visit for Fever",
            archive_type="visit",
            status="final",
        )

        PatientArchive.objects.filter(
            pk=self.archive1.pk
        ).update(
            created_at=now - timedelta(days=10)
        )
        PatientArchive.objects.filter(
            pk=self.archive2.pk
        ).update(
            created_at=now - timedelta(days=5)
        )
        PatientArchive.objects.filter(
            pk=self.archive3.pk
        ).update(
            created_at=now
        )

    def test_search_by_title(self):
        response = self.client.get(
            reverse(
                "medical_archive:archive_list"
            ),
            {"search": "Diabetes"},
        )

        self.assertContains(
            response,
            "Diabetes Lab",
        )
        self.assertNotContains(
            response,
            "Chest Scan Result",
        )
        self.assertNotContains(
            response,
            "Visit for Fever",
        )

    def test_filter_by_type(self):
        response = self.client.get(
            reverse(
                "medical_archive:archive_list"
            ),
            {"type": "scan"},
        )

        self.assertContains(
            response,
            "Chest Scan Result",
        )
        self.assertNotContains(
            response,
            "Diabetes Lab",
        )
        self.assertNotContains(
            response,
            "Visit for Fever",
        )

    def test_filter_by_date_range(self):
        today = timezone.localdate()

        response = self.client.get(
            reverse(
                "medical_archive:archive_list"
            ),
            {
                "start_date":
                (
                    today - timedelta(days=6)
                ).isoformat()
            },
        )

        self.assertContains(
            response,
            "Chest Scan Result",
        )
        self.assertContains(
            response,
            "Visit for Fever",
        )
        self.assertNotContains(
            response,
            "Diabetes Lab",
        )

        response2 = self.client.get(
            reverse(
                "medical_archive:archive_list"
            ),
            {
                "start_date": today.isoformat(),
                "end_date": today.isoformat(),
            },
        )

        self.assertContains(
            response2,
            "Visit for Fever",
        )
        self.assertNotContains(
            response2,
            "Diabetes Lab",
        )
        self.assertNotContains(
            response2,
            "Chest Scan Result",
        )
