from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse

from accounts.tests.permission_utils import (
    apply_role_permissions,
)
from doctor.models import Doctor
from medical_archive.models import PatientArchive
from patient.models import Patient


User = get_user_model()


class ArchiveAccessPermissionTests(TestCase):
    def setUp(self):
        self.user1 = User.objects.create_user(
            email="patient1@test.com",
            password="pass",
            username="pat1",
            role="patient",
            is_approved=True,
        )
        self.patient1, _ = Patient.objects.update_or_create(
            user=self.user1,
            defaults={"full_name": "Ali Ahmed"},
        )
        apply_role_permissions(self.user1)

        self.doctor_user = User.objects.create_user(
            email="doc@test.com",
            password="pass",
            username="doc",
            role="doctor",
            is_approved=True,
        )
        self.doctor = Doctor.objects.create(
            user=self.doctor_user,
            full_name="Dr. Test",
            specialty="Cardiology",
        )
        apply_role_permissions(self.doctor_user)

        self.user2 = User.objects.create_user(
            email="patient2@test.com",
            password="pass",
            username="pat2",
            role="patient",
            is_approved=True,
        )
        self.patient2, _ = Patient.objects.update_or_create(
            user=self.user2,
            defaults={"full_name": "Zainab Other"},
        )
        apply_role_permissions(self.user2)

        self.archive = PatientArchive.objects.create(
            patient=self.patient1,
            doctor=self.doctor,
            title="Private record",
            archive_type="visit",
            status="final",
        )

    def _archive_url(self):
        return reverse(
            "medical_archive:archive_detail",
            kwargs={"archive_id": self.archive.pk},
        )

    def test_patient_cannot_access_other_patient_archive(self):
        client = Client()
        client.login(
            email="patient2@test.com",
            password="pass",
        )

        response = client.get(self._archive_url())

        self.assertIn(
            response.status_code,
            (403, 404),
        )

    def test_patient_can_access_own_archive(self):
        client = Client()
        client.login(
            email="patient1@test.com",
            password="pass",
        )

        response = client.get(self._archive_url())

        self.assertEqual(
            response.status_code,
            200,
        )

    def test_non_authenticated_user_cannot_access_archive(self):
        response = Client().get(
            self._archive_url()
        )

        self.assertIn(
            response.status_code,
            (302, 403, 404),
        )

    def test_doctor_can_access_patient_archive(self):
        client = Client()
        client.login(
            email="doc@test.com",
            password="pass",
        )

        response = client.get(self._archive_url())

        self.assertEqual(
            response.status_code,
            200,
        )

    def test_random_user_cannot_access_any_archive(self):
        random_user = User.objects.create_user(
            email="random@test.com",
            password="pass",
            username="rnd",
            role="patient",
            is_approved=True,
        )
        apply_role_permissions(random_user)

        client = Client()
        client.login(
            email="random@test.com",
            password="pass",
        )

        response = client.get(self._archive_url())

        self.assertIn(
            response.status_code,
            (403, 404),
        )
