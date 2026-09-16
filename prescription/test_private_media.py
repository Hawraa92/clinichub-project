from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
from datetime import timedelta
from pathlib import Path

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from appointments.models import Appointment, AppointmentStatus
from core.private_storage import private_clinical_storage
from doctor.models import Doctor
from hospital.models import Branch, Hospital, StaffAssignment
from patient.models import Patient

from .management.commands.relocate_clinical_media import FIELD_SPECS
from .models import Prescription


User = get_user_model()


@override_settings(
    MEDIA_ROOT=tempfile.mkdtemp(prefix="prescription-media-"),
    PRIVATE_MEDIA_ROOT=tempfile.mkdtemp(prefix="private-clinical-media-"),
)
class PrescriptionPrivateMediaTests(TestCase):
    password = "PrivateMediaPass123!"

    @classmethod
    def tearDownClass(cls):
        media_root = cls._overridden_settings["MEDIA_ROOT"]
        private_root = cls._overridden_settings["PRIVATE_MEDIA_ROOT"]
        super().tearDownClass()
        shutil.rmtree(media_root, ignore_errors=True)
        shutil.rmtree(private_root, ignore_errors=True)

    def setUp(self):
        self.client = Client()
        self.hospital_a = Hospital.objects.create(name="Private A", code="PRIVATE-A")
        self.branch_a = Branch.objects.create(
            hospital=self.hospital_a,
            name="Private Branch A",
            code="PRIVATE-A1",
        )
        self.hospital_b = Hospital.objects.create(name="Private B", code="PRIVATE-B")
        self.branch_b = Branch.objects.create(
            hospital=self.hospital_b,
            name="Private Branch B",
            code="PRIVATE-B1",
        )
        self.doctor_a = self._doctor("private-doctor-a@example.test", self.hospital_a, self.branch_a)
        self.doctor_b = self._doctor("private-doctor-b@example.test", self.hospital_b, self.branch_b)
        self.patient_a = self._patient("private-patient-a@example.test", "Private Patient A")
        self.patient_b = self._patient("private-patient-b@example.test", "Private Patient B")
        self.prescription_a = self._prescription(self.doctor_a, self.patient_a, self.hospital_a, self.branch_a)
        self.prescription_b = self._prescription(self.doctor_b, self.patient_b, self.hospital_b, self.branch_b)
        permission = Permission.objects.get(
            content_type__app_label="prescription",
            codename="view_prescription",
        )
        self.doctor_a.user.user_permissions.add(permission)
        self.doctor_b.user.user_permissions.add(permission)
        self._clear_permission_cache(self.doctor_a.user)
        self._clear_permission_cache(self.doctor_b.user)

    def _doctor(self, email, hospital, branch):
        user = User.objects.create_user(
            email=email,
            password=self.password,
            role="doctor",
            is_approved=True,
        )
        doctor = Doctor.objects.create(user=user, full_name=email)
        StaffAssignment.objects.create(
            user=user,
            hospital=hospital,
            branch=branch,
            role=StaffAssignment.Roles.DOCTOR,
            is_primary=True,
            is_active=True,
        )
        return doctor

    def _patient(self, email, name):
        user = User.objects.create_user(
            email=email,
            password=self.password,
            role="patient",
            is_approved=True,
        )
        patient = Patient.objects.get(user=user)
        patient.full_name = name
        patient.save(update_fields=["full_name"])
        return patient

    def _prescription(self, doctor, patient, hospital, branch):
        appointment = Appointment.objects.create(
            doctor=doctor,
            patient=patient,
            hospital=hospital,
            branch=branch,
            scheduled_time=timezone.now() + timedelta(days=1),
            status=AppointmentStatus.PENDING,
        )
        prescription = Prescription.objects.create(
            appointment=appointment,
            doctor=doctor,
            patient=patient,
            patient_full_name=patient.full_name,
            age=35,
        )
        prescription.voice_note.save(
            "patient-original-name.mp3",
            SimpleUploadedFile("patient-original-name.mp3", b"voice-data", content_type="audio/mpeg"),
            save=True,
        )
        return prescription

    @staticmethod
    def _clear_permission_cache(user):
        for name in ("_perm_cache", "_user_perm_cache", "_group_perm_cache"):
            user.__dict__.pop(name, None)

    def test_authorized_attachment_uses_neutral_filename_and_private_headers(self):
        self.client.force_login(self.doctor_a.user)
        response = self.client.get(
            reverse(
                "prescription:attachment",
                args=[self.prescription_a.pk, "voice_note"],
            )
        )
        self.assertEqual(response.status_code, 200)
        cache_control = response["Cache-Control"]
        self.assertIn("private", cache_control)
        self.assertIn("no-store", cache_control)
        self.assertEqual(response["X-Content-Type-Options"], "nosniff")
        self.assertIn("prescription-", response["Content-Disposition"])
        self.assertIn("voice-note", response["Content-Disposition"])
        self.assertNotIn("patient-original-name", response["Content-Disposition"])
        self.assertNotIn("voice_notes/", response["Content-Disposition"])

    def test_anonymous_and_foreign_users_are_denied(self):
        url = reverse("prescription:attachment", args=[self.prescription_a.pk, "voice_note"])
        self.assertEqual(self.client.get(url).status_code, 302)

        self.client.force_login(self.doctor_b.user)
        self.assertIn(self.client.get(url).status_code, (403, 404))

    def test_unsupported_or_missing_attachment_is_not_exposed(self):
        self.client.force_login(self.doctor_a.user)
        unsupported = reverse("prescription:attachment", args=[self.prescription_a.pk, "doctor_logo"])
        self.assertEqual(self.client.get(unsupported).status_code, 404)

        self.prescription_a.qr_code.save(
            "original-qr-name.png",
            SimpleUploadedFile("original-qr-name.png", b"qr-data", content_type="image/png"),
            save=True,
        )
        stored_name = self.prescription_a.qr_code.name
        self.assertTrue(self.prescription_a.qr_code.storage.exists(stored_name))
        self.prescription_a.qr_code.storage.delete(stored_name)
        self.prescription_a.refresh_from_db()
        self.assertEqual(self.prescription_a.qr_code.name, stored_name)
        missing = reverse("prescription:attachment", args=[self.prescription_a.pk, "qr_code"])
        self.assertEqual(self.client.get(missing).status_code, 404)

    def test_private_storage_has_no_public_url(self):
        with self.assertRaises(ValueError):
            private_clinical_storage.url("prescriptions/example.pdf")

    def test_report_template_uses_authorized_route(self):
        template = Path(__file__).resolve().parents[1] / "templates" / "doctor" / "report_patient.html"
        contents = template.read_text(encoding="utf-8")
        self.assertNotIn("p.pdf_file.url", contents)
        self.assertIn("prescription:download_pdf", contents)

    def test_public_branding_is_not_in_relocation_allowlist(self):
        self.assertNotIn((Doctor, "photo"), FIELD_SPECS)
        self.assertNotIn((Doctor, "cover_photo"), FIELD_SPECS)
        self.assertNotIn((Doctor, "clinic_logo"), FIELD_SPECS)

    def test_medical_archive_is_not_in_relocation_allowlist(self):
        self.assertFalse(
            any(model._meta.app_label == "medical_archive" for model, _field in FIELD_SPECS)
        )

    def test_relocation_without_flags_is_report_only(self):
        source_name = self.prescription_a.voice_note.name
        destination = Path(private_clinical_storage.path(source_name))
        self.assertFalse(destination.exists())
        call_command("relocate_clinical_media")
        self.assertFalse(destination.exists())
        self.prescription_a.refresh_from_db()
        self.assertEqual(self.prescription_a.voice_note.name, source_name)

    def test_execute_copies_without_changing_database_name_and_is_idempotent(self):
        source_name = self.prescription_a.voice_note.name
        source_path = Path(self.prescription_a.voice_note.path)
        expected_hash = hashlib.sha256(source_path.read_bytes()).hexdigest()
        call_command("relocate_clinical_media", "--execute")
        destination = Path(private_clinical_storage.path(source_name))
        self.assertTrue(destination.exists())
        self.assertEqual(hashlib.sha256(destination.read_bytes()).hexdigest(), expected_hash)
        self.prescription_a.refresh_from_db()
        self.assertEqual(self.prescription_a.voice_note.name, source_name)
        call_command("relocate_clinical_media", "--execute")
        self.assertEqual(hashlib.sha256(destination.read_bytes()).hexdigest(), expected_hash)

    def test_missing_source_is_reported(self):
        source_name = self.prescription_a.voice_note.name
        Path(self.prescription_a.voice_note.path).unlink()
        output = __import__("io").StringIO()
        call_command("relocate_clinical_media", stdout=output)
        payload = json.loads(output.getvalue())
        self.assertTrue(any(record["status"] == "missing_source" for record in payload["records"]))
        self.assertEqual(self.prescription_a.voice_note.name, source_name)

    def test_conflict_is_not_overwritten(self):
        source_name = self.prescription_a.voice_note.name
        destination = Path(private_clinical_storage.path(source_name))
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(b"unexpected-destination")
        output = __import__("io").StringIO()
        call_command("relocate_clinical_media", "--execute", stdout=output)
        payload = json.loads(output.getvalue())
        self.assertTrue(any(record["status"] == "conflict" for record in payload["records"]))
        self.assertEqual(destination.read_bytes(), b"unexpected-destination")
