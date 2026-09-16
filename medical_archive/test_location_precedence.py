from datetime import timedelta

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from appointments.models import Appointment
from doctor.models import Doctor
from hospital.models import Branch, Hospital, StaffAssignment
from patient.models import Patient

from medical_archive.models import (
    ArchiveAttachment,
    ArchiveVoiceNote,
    PatientArchive,
)


User = get_user_model()


class ArchiveLocationPrecedenceTests(TestCase):
    password = "StrongTestPass123!"

    def setUp(self):
        self.client = Client()

        self.hospital = Hospital.objects.create(
            name="Location Precedence Hospital",
            code="ARCH-LOC-HOSP",
            is_active=True,
        )

        self.branch_a = Branch.objects.create(
            hospital=self.hospital,
            name="Location Branch A",
            code="ARCH-LOC-A",
            is_active=True,
        )

        self.branch_b = Branch.objects.create(
            hospital=self.hospital,
            name="Location Branch B",
            code="ARCH-LOC-B",
            is_active=True,
        )

        doctor_user = User.objects.create_user(
            email="location-doctor@test.com",
            username="location_doctor",
            password=self.password,
            role="doctor",
            is_approved=True,
        )

        self.doctor = Doctor.objects.create(
            user=doctor_user,
            full_name="Shared Location Doctor",
            specialty="General",
        )

        # The doctor works in both branches.
        StaffAssignment.objects.create(
            user=doctor_user,
            hospital=self.hospital,
            branch=self.branch_a,
            role=StaffAssignment.Roles.DOCTOR,
            is_primary=True,
            is_active=True,
        )

        StaffAssignment.objects.create(
            user=doctor_user,
            hospital=self.hospital,
            branch=self.branch_b,
            role=StaffAssignment.Roles.DOCTOR,
            is_primary=False,
            is_active=True,
        )

        patient_user = User.objects.create_user(
            email="location-patient@test.com",
            username="location_patient",
            password=self.password,
            role="patient",
            is_approved=True,
        )

        self.patient, _created = Patient.objects.update_or_create(
            user=patient_user,
            defaults={
                "full_name": "Location Precedence Patient",
                "doctor": self.doctor,
            },
        )

        # The appointment belongs specifically to branch B.
        self.foreign_appointment = Appointment.objects.create(
            patient=self.patient,
            doctor=self.doctor,
            hospital=self.hospital,
            branch=self.branch_b,
            scheduled_time=timezone.now() + timedelta(days=2),
            iqd_amount=0,
        )

        self.foreign_archive = PatientArchive.objects.create(
            patient=self.patient,
            doctor=self.doctor,
            appointment=self.foreign_appointment,
            title="Branch B Appointment Archive",
            archive_type="visit",
            status="final",
        )

        self.secretary_a = User.objects.create_user(
            email="location-secretary-a@test.com",
            username="location_secretary_a",
            password=self.password,
            role="secretary",
            is_approved=True,
        )

        StaffAssignment.objects.create(
            user=self.secretary_a,
            hospital=self.hospital,
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

        self.secretary_a.user_permissions.add(*permissions)
        self.client.force_login(self.secretary_a)

    def test_branch_a_list_hides_branch_b_archive(self):
        response = self.client.get(
            reverse("medical_archive:archive_list")
        )

        self.assertEqual(response.status_code, 200)

        visible_ids = {
            archive.pk
            for archive
            in response.context["page_obj"].object_list
        }

        self.assertNotIn(
            self.foreign_archive.pk,
            visible_ids,
        )

    def test_branch_a_cannot_open_branch_b_archive(self):
        response = self.client.get(
            reverse(
                "medical_archive:archive_detail",
                kwargs={
                    "archive_id": self.foreign_archive.pk,
                },
            )
        )

        self.assertEqual(response.status_code, 404)

    def test_created_by_does_not_bypass_appointment_branch_scope(self):
        """
        A branch-A staff member must not gain access to a branch-B
        appointment archive merely because they are its creator.
        """
        self.foreign_archive.created_by = self.secretary_a
        self.foreign_archive.save(
            update_fields=["created_by"],
        )

        attachment = ArchiveAttachment.objects.create(
            archive=self.foreign_archive,
            file=SimpleUploadedFile(
                "foreign-branch-report.pdf",
                b"%PDF-1.4 foreign branch report",
                content_type="application/pdf",
            ),
            description="Foreign branch attachment",
        )

        voice_note = ArchiveVoiceNote.objects.create(
            archive=self.foreign_archive,
            audio=SimpleUploadedFile(
                "foreign-branch-note.mp3",
                b"foreign-branch-audio",
                content_type="audio/mpeg",
            ),
            title="Foreign branch voice note",
        )

        list_response = self.client.get(
            reverse("medical_archive:archive_list")
        )

        self.assertEqual(
            list_response.status_code,
            200,
        )

        visible_ids = {
            archive.pk
            for archive
            in list_response.context[
                "page_obj"
            ].object_list
        }

        self.assertNotIn(
            self.foreign_archive.pk,
            visible_ids,
        )

        detail_response = self.client.get(
            reverse(
                "medical_archive:archive_detail",
                kwargs={
                    "archive_id":
                    self.foreign_archive.pk,
                },
            )
        )

        self.assertEqual(
            detail_response.status_code,
            404,
        )

        attachment_response = self.client.get(
            reverse(
                "medical_archive:preview_attachment",
                kwargs={
                    "attachment_id":
                    attachment.pk,
                },
            )
        )

        self.assertEqual(
            attachment_response.status_code,
            404,
        )

        voice_response = self.client.get(
            reverse(
                "medical_archive:stream_voice_note",
                kwargs={
                    "voice_id":
                    voice_note.pk,
                },
            )
        )

        self.assertEqual(
            voice_response.status_code,
            404,
        )
