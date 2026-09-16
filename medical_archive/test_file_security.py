from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase
from django.urls import reverse

from doctor.models import Doctor
from hospital.models import (
    Branch,
    Hospital,
    StaffAssignment,
)
from patient.models import Patient

from medical_archive.forms import PatientArchiveForm
from medical_archive.models import (
    ArchiveAttachment,
    ArchiveVoiceNote,
    PatientArchive,
)


User = get_user_model()


class MedicalArchiveFileSecurityTests(TestCase):
    password = "StrongTestPass123!"

    def setUp(self):
        self.client = Client()

        self.hospital_a = Hospital.objects.create(
            name="Archive Hospital A",
            code="ARCH-HOSP-A",
            is_active=True,
        )
        self.branch_a = Branch.objects.create(
            hospital=self.hospital_a,
            name="Archive Branch A",
            code="ARCH-BR-A",
            is_active=True,
        )

        self.hospital_b = Hospital.objects.create(
            name="Archive Hospital B",
            code="ARCH-HOSP-B",
            is_active=True,
        )
        self.branch_b = Branch.objects.create(
            hospital=self.hospital_b,
            name="Archive Branch B",
            code="ARCH-BR-B",
            is_active=True,
        )

        self.doctor_a = self._create_doctor(
            "archive-doctor-a@test.com",
            "archive_doctor_a",
            self.hospital_a,
            self.branch_a,
        )
        self.doctor_b = self._create_doctor(
            "archive-doctor-b@test.com",
            "archive_doctor_b",
            self.hospital_b,
            self.branch_b,
        )

        self.patient_a = self._create_patient(
            "archive-patient-a@test.com",
            "archive_patient_a",
            "Archive Patient A",
            self.doctor_a,
        )
        self.patient_b = self._create_patient(
            "archive-patient-b@test.com",
            "archive_patient_b",
            "Archive Patient B",
            self.doctor_b,
        )

        self.archive_a = PatientArchive.objects.create(
            patient=self.patient_a,
            doctor=self.doctor_a,
            title="Archive A",
            archive_type="visit",
            status="final",
        )
        self.archive_b = PatientArchive.objects.create(
            patient=self.patient_b,
            doctor=self.doctor_b,
            title="Archive B",
            archive_type="visit",
            status="final",
        )

        self.attachment_a = (
            ArchiveAttachment.objects.create(
                archive=self.archive_a,
                file=SimpleUploadedFile(
                    "archive-a.jpg",
                    b"secure-image-a",
                    content_type="image/jpeg",
                ),
                description="Secure image A",
            )
        )
        self.attachment_b = (
            ArchiveAttachment.objects.create(
                archive=self.archive_b,
                file=SimpleUploadedFile(
                    "archive-b.jpg",
                    b"secure-image-b",
                    content_type="image/jpeg",
                ),
                description="Secure image B",
            )
        )

        self.voice_a = ArchiveVoiceNote.objects.create(
            archive=self.archive_a,
            audio=SimpleUploadedFile(
                "archive-a.mp3",
                b"secure-audio-a",
                content_type="audio/mpeg",
            ),
            title="Secure voice A",
        )
        self.voice_b = ArchiveVoiceNote.objects.create(
            archive=self.archive_b,
            audio=SimpleUploadedFile(
                "archive-b.mp3",
                b"secure-audio-b",
                content_type="audio/mpeg",
            ),
            title="Secure voice B",
        )

        self.secretary = User.objects.create_user(
            email="archive-secretary@test.com",
            username="archive_secretary",
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

        permissions = Permission.objects.filter(
            content_type__app_label="medical_archive",
            codename__in=[
                "view_patientarchive",
                "view_archiveattachment",
                "view_archivevoicenote",
            ],
        )
        self.secretary.user_permissions.add(
            *permissions
        )

        self.client.force_login(
            self.secretary
        )

    def _create_doctor(
        self,
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

        return doctor

    def _create_patient(
        self,
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

        patient, _created = (
            Patient.objects.update_or_create(
                user=user,
                defaults={
                    "full_name": full_name,
                    "doctor": doctor,
                },
            )
        )

        return patient

    def test_secretary_list_is_branch_isolated(self):
        response = self.client.get(
            reverse(
                "medical_archive:archive_list"
            )
        )

        self.assertEqual(
            response.status_code,
            200,
        )

        visible_ids = {
            archive.pk
            for archive
            in response.context[
                "page_obj"
            ].object_list
        }

        self.assertEqual(
            visible_ids,
            {self.archive_a.pk},
        )

    def test_secretary_cannot_open_foreign_archive(self):
        response = self.client.get(
            reverse(
                "medical_archive:archive_detail",
                kwargs={
                    "archive_id":
                    self.archive_b.pk,
                },
            )
        )

        self.assertEqual(
            response.status_code,
            404,
        )

    def test_secretary_cannot_preview_foreign_attachment(self):
        response = self.client.get(
            reverse(
                "medical_archive:preview_attachment",
                kwargs={
                    "attachment_id":
                    self.attachment_b.pk,
                },
            )
        )

        self.assertEqual(
            response.status_code,
            404,
        )

    def test_secretary_cannot_stream_foreign_voice(self):
        response = self.client.get(
            reverse(
                "medical_archive:stream_voice_note",
                kwargs={
                    "voice_id":
                    self.voice_b.pk,
                },
            )
        )

        self.assertEqual(
            response.status_code,
            404,
        )

    def test_secretary_can_preview_assigned_attachment(self):
        response = self.client.get(
            reverse(
                "medical_archive:preview_attachment",
                kwargs={
                    "attachment_id":
                    self.attachment_a.pk,
                },
            )
        )

        self.assertEqual(
            response.status_code,
            200,
        )
        self.assertEqual(
            response["Cache-Control"],
            "private, no-store, max-age=0",
        )

    def test_archive_template_has_no_direct_media_link(self):
        response = self.client.get(
            reverse(
                "medical_archive:archive_detail",
                kwargs={
                    "archive_id":
                    self.archive_a.pk,
                },
            )
        )

        self.assertEqual(
            response.status_code,
            200,
        )
        self.assertNotContains(
            response,
            "/media/patient_archives/",
        )

    def test_doctor_form_excludes_foreign_patient(self):
        form = PatientArchiveForm(
            user=self.doctor_a.user,
        )

        visible_ids = set(
            form.fields["patient"]
            .queryset
            .values_list("pk", flat=True)
        )

        self.assertEqual(
            visible_ids,
            {self.patient_a.pk},
        )

    def test_doctor_post_cannot_select_foreign_patient(self):
        form = PatientArchiveForm(
            data={
                "patient": self.patient_b.pk,
                "title": "Illegal foreign archive",
                "notes": "",
                "archive_type": "visit",
                "is_critical": False,
            },
            user=self.doctor_a.user,
        )

        self.assertFalse(form.is_valid())
        self.assertIn(
            "patient",
            form.errors,
        )

    def test_file_storage_has_no_public_url(self):
        with self.assertRaises(ValueError):
            _url = self.attachment_a.file.url
