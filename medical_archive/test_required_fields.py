# medical_archive/test_required_fields.py

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase

from doctor.models import Doctor
from medical_archive.models import PatientArchive
from patient.models import Patient

User = get_user_model()


class RequiredFieldsTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="test@test.com",
            password="pass",
            username="user",
        )
        self.doctor = Doctor.objects.create(
            user=self.user,
            full_name="Dr. Test",
            specialty="Neuro",
        )
        self.patient, _ = Patient.objects.update_or_create(
            user=self.user,
            defaults={"full_name": "Ali Required"},
        )

    def test_missing_title_is_rejected(self):
        archive = PatientArchive(
            patient=self.patient,
            doctor=self.doctor,
            title="",
            archive_type="visit",
            status="final",
        )

        with self.assertRaises(ValidationError):
            archive.full_clean()

    def test_draft_without_doctor_is_allowed(self):
        archive = PatientArchive(
            patient=self.patient,
            doctor=None,
            title="Draft Without Doctor",
            archive_type="visit",
            status="draft",
        )

        archive.full_clean()

    def test_draft_without_patient_is_allowed(self):
        archive = PatientArchive(
            patient=None,
            doctor=self.doctor,
            title="Draft Without Patient",
            archive_type="visit",
            status="draft",
        )

        archive.full_clean()
