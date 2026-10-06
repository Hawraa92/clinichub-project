import base64
import tempfile

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from doctor.models import Doctor
from hospital.models import Branch, Hospital, StaffAssignment
from medical_archive.models import ArchiveAttachment, PatientArchive
from medical_archive.test_support import grant_archive_permissions
from patient.models import Patient


User = get_user_model()


class QuickClinicalHandoffTests(TestCase):
    password = "StrongTestPass123!"

    def setUp(self):
        self.temp_media = tempfile.TemporaryDirectory()
        self.media_override = override_settings(
            MEDIA_ROOT=self.temp_media.name
        )
        self.media_override.enable()

        self.client = Client()

        self.hospital_a = Hospital.objects.create(
            name="Quick Handoff Hospital A",
            code="QH-HOSP-A",
            is_active=True,
        )
        self.branch_a = Branch.objects.create(
            hospital=self.hospital_a,
            name="Quick Handoff Branch A",
            code="QH-BR-A",
            is_active=True,
        )

        self.hospital_b = Hospital.objects.create(
            name="Quick Handoff Hospital B",
            code="QH-HOSP-B",
            is_active=True,
        )
        self.branch_b = Branch.objects.create(
            hospital=self.hospital_b,
            name="Quick Handoff Branch B",
            code="QH-BR-B",
            is_active=True,
        )

        self.doctor_a = self._create_doctor(
            email="quick-doctor-a@test.com",
            username="quick_doctor_a",
            hospital=self.hospital_a,
            branch=self.branch_a,
        )
        self.doctor_b = self._create_doctor(
            email="quick-doctor-b@test.com",
            username="quick_doctor_b",
            hospital=self.hospital_b,
            branch=self.branch_b,
        )

        self.patient_a = self._create_patient(
            email="quick-patient-a@test.com",
            username="quick_patient_a",
            full_name="Quick Patient A",
            doctor=self.doctor_a,
        )
        self.patient_b = self._create_patient(
            email="quick-patient-b@test.com",
            username="quick_patient_b",
            full_name="Quick Patient B",
            doctor=self.doctor_b,
        )

        self.secretary = User.objects.create_user(
            email="quick-secretary@test.com",
            username="quick_secretary",
            password=self.password,
            role="secretary",
            is_approved=True,
        )

        StaffAssignment.objects.create(
            user=self.secretary,
            hospital=self.hospital_a,
            branch=self.branch_a,
            role=StaffAssignment.Roles.SECRETARY,
            is_primary=True,
            is_active=True,
        )

        codenames = {
            "add_patientarchive",
            "add_archiveattachment",
        }

        permissions = list(
            Permission.objects.filter(
                content_type__app_label="medical_archive",
                codename__in=codenames,
            )
        )

        self.assertEqual(
            {permission.codename for permission in permissions},
            codenames,
        )

        self.secretary.user_permissions.add(*permissions)

        self.client.force_login(self.secretary)

        self.url = reverse(
            "medical_archive:quick_send_to_doctor"
        )

    def tearDown(self):
        self.media_override.disable()
        self.temp_media.cleanup()
        super().tearDown()

    def _create_doctor(
        self,
        *,
        email,
        username,
        hospital,
        branch,
    ):
        user = User.objects.create_user(
            email=email,
            username=username,
            password=self.password,
            role="doctor",
            is_approved=True,
        )

        doctor = Doctor.objects.create(
            user=user,
            full_name=username,
            specialty="General",
        )

        StaffAssignment.objects.create(
            user=user,
            hospital=hospital,
            branch=branch,
            role=StaffAssignment.Roles.DOCTOR,
            is_primary=True,
            is_active=True,
        )

        grant_archive_permissions(user)

        return doctor

    def _create_patient(
        self,
        *,
        email,
        username,
        full_name,
        doctor,
    ):
        user = User.objects.create_user(
            email=email,
            username=username,
            password=self.password,
            role="patient",
            is_approved=True,
        )

        patient, _created = Patient.objects.update_or_create(
            user=user,
            defaults={
                "full_name": full_name,
                "doctor": doctor,
            },
        )

        return patient

    def _ecg_file(self):
        png_bytes = base64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwC"
            "AAAAC0lEQVR42mP8/x8AAusB9WlN5V8AAAAASUVORK5CYII="
        )

        return SimpleUploadedFile(
            "synthetic-ecg.png",
            png_bytes,
            content_type="image/png",
        )

    def _post_handoff(
        self,
        *,
        patient,
        doctor,
    ):
        return self.client.post(
            self.url,
            {
                "patient_id": patient.pk,
                "doctor_id": doctor.pk,
                "clinical_type": "ecg",
                "note": "Synthetic ECG handoff test.",
                "files": self._ecg_file(),
            },
        )

    def test_secretary_can_send_ecg_to_assigned_doctor(self):
        response = self._post_handoff(
            patient=self.patient_a,
            doctor=self.doctor_a,
        )

        self.assertEqual(response.status_code, 200)

        archive = PatientArchive.objects.get()

        self.assertEqual(archive.patient, self.patient_a)
        self.assertEqual(archive.doctor, self.doctor_a)
        self.assertEqual(archive.title, "ECG Recording")
        self.assertEqual(archive.archive_type, "scan")
        self.assertEqual(archive.status, "final")
        self.assertEqual(
            archive.notes,
            "Synthetic ECG handoff test.",
        )
        self.assertEqual(
            archive.created_by,
            self.secretary,
        )
        self.assertEqual(
            archive.updated_by,
            self.secretary,
        )

        attachment = ArchiveAttachment.objects.get(
            archive=archive
        )

        self.assertEqual(
            attachment.description,
            "ECG recording",
        )
        self.assertEqual(
            attachment.uploaded_by,
            self.secretary,
        )

        self.assertFalse(
            self.secretary.has_perm(
                "medical_archive.view_patientarchive"
            )
        )

        detail_url = reverse(
            "medical_archive:archive_detail",
            kwargs={"archive_id": archive.pk},
        )

        secretary_response = self.client.get(detail_url)
        self.assertEqual(
            secretary_response.status_code,
            403,
        )

        self.client.force_login(self.doctor_a.user)

        doctor_response = self.client.get(detail_url)
        self.assertEqual(
            doctor_response.status_code,
            200,
        )

    def test_secretary_cannot_send_foreign_patient(self):
        response = self._post_handoff(
            patient=self.patient_b,
            doctor=self.doctor_a,
        )

        self.assertEqual(response.status_code, 404)
        self.assertFalse(
            PatientArchive.objects.exists()
        )
        self.assertFalse(
            ArchiveAttachment.objects.exists()
        )

    def test_secretary_cannot_send_to_foreign_doctor(self):
        response = self._post_handoff(
            patient=self.patient_a,
            doctor=self.doctor_b,
        )

        self.assertEqual(response.status_code, 404)
        self.assertFalse(
            PatientArchive.objects.exists()
        )
        self.assertFalse(
            ArchiveAttachment.objects.exists()
        )

    def test_add_attachment_permission_is_required(self):
        permission = Permission.objects.get(
            content_type__app_label="medical_archive",
            codename="add_archiveattachment",
        )

        self.secretary.user_permissions.remove(permission)

        for cache_name in (
            "_perm_cache",
            "_user_perm_cache",
            "_group_perm_cache",
        ):
            self.secretary.__dict__.pop(
                cache_name,
                None,
            )

        response = self._post_handoff(
            patient=self.patient_a,
            doctor=self.doctor_a,
        )

        self.assertEqual(response.status_code, 403)
        self.assertFalse(
            PatientArchive.objects.exists()
        )
        self.assertFalse(
            ArchiveAttachment.objects.exists()
        )
