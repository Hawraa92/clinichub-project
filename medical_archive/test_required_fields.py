from __future__ import annotations

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase

from doctor.models import Doctor
from patient.models import Patient
from medical_archive.models import PatientArchive

User = get_user_model()


class RequiredFieldsTests(TestCase):
    def _maybe_set_user_fields(self, user, **fields) -> None:
        """Set optional custom fields (role/is_approved/...) only if they exist."""
        update_fields = []
        for k, v in fields.items():
            if hasattr(user, k):
                setattr(user, k, v)
                update_fields.append(k)
        if update_fields:
            user.save(update_fields=update_fields)

    def _get_or_create_patient(self, user, full_name: str) -> Patient:
        """
        عندك ممكن Signals تسوي Patient تلقائياً للمستخدم.
        نستخدم get_or_create لتفادي unique(user) conflicts.
        """
        patient, _ = Patient.objects.get_or_create(user=user, defaults={"full_name": full_name})
        if getattr(patient, "full_name", "") != full_name:
            patient.full_name = full_name
            patient.save(update_fields=["full_name"])
        return patient

    def _get_or_create_doctor(self, user, full_name: str, specialty: str) -> Doctor:
        """
        نفس الفكرة: ممكن Signals أو قيود تمنع التكرار.
        """
        doctor, _ = Doctor.objects.get_or_create(
            user=user,
            defaults={"full_name": full_name, "specialty": specialty},
        )
        dirty = False
        if hasattr(doctor, "full_name") and doctor.full_name != full_name:
            doctor.full_name = full_name
            dirty = True
        if hasattr(doctor, "specialty") and getattr(doctor, "specialty", None) != specialty:
            doctor.specialty = specialty
            dirty = True
        if dirty:
            doctor.save()
        return doctor

    def setUp(self):
        # ✅ لا تستخدم نفس المستخدم للطبيب والمريض (أكثر واقعية + أقل تعارضات)
        self.doctor_user = User.objects.create_user(email="doc_req@test.com", password="pass", username="doc_req")
        self.patient_user = User.objects.create_user(email="pat_req@test.com", password="pass", username="pat_req")

        self._maybe_set_user_fields(self.doctor_user, role="doctor", is_approved=True, is_active=True)
        self._maybe_set_user_fields(self.patient_user, role="patient", is_approved=True, is_active=True)

        self.doctor = self._get_or_create_doctor(self.doctor_user, full_name="Dr. Test", specialty="Neuro")
        self.patient = self._get_or_create_patient(self.patient_user, full_name="Ali Required")

    # -------------------------
    # Title is always required
    # -------------------------
    def test_missing_title(self):
        archive = PatientArchive(
            patient=self.patient,
            doctor=self.doctor,
            title="",
            archive_type="visit",
            status="final",
        )
        with self.assertRaises(ValidationError):
            archive.full_clean()

    # ---------------------------------------------
    # Draft MAY allow missing doctor/patient (model allows null/blank)
    # ---------------------------------------------
    def test_draft_allows_missing_doctor(self):
        archive = PatientArchive(
            patient=self.patient,
            doctor=None,
            title="Draft Without Doctor",
            archive_type="visit",
            status="draft",
        )
        # ✅ يجب لا يرفع ValidationError طالما draft
        archive.full_clean()

    def test_draft_allows_missing_patient(self):
        archive = PatientArchive(
            patient=None,
            doctor=self.doctor,
            title="Draft Without Patient",
            archive_type="visit",
            status="draft",
        )
        archive.full_clean()

    # -------------------------------------------------------
    # Final SHOULD require doctor/patient (needs model clean() rule)
    # -------------------------------------------------------
    def test_final_requires_doctor(self):
        archive = PatientArchive(
            patient=self.patient,
            doctor=None,
            title="Final Without Doctor",
            archive_type="visit",
            status="final",
        )
        with self.assertRaises(ValidationError):
            archive.full_clean()

    def test_final_requires_patient(self):
        archive = PatientArchive(
            patient=None,
            doctor=self.doctor,
            title="Final Without Patient",
            archive_type="visit",
            status="final",
        )
        with self.assertRaises(ValidationError):
            archive.full_clean()
