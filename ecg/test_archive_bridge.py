import io
import tempfile

from PIL import Image

from django.contrib.auth.models import Permission
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from appointments.tests.factories import (
    AppointmentFactory,
    DoctorFactory,
    PatientFactory,
)
from medical_archive.models import (
    ArchiveAttachment,
    PatientArchive,
)

from ecg.models import ECGFile, ECGRecord


BRIDGE_PERMISSIONS = (
    (
        "medical_archive",
        "view_patientarchive",
    ),
    (
        "medical_archive",
        "view_archiveattachment",
    ),
    (
        "ecg",
        "view_ecgrecord",
    ),
    (
        "ecg",
        "add_ecgrecord",
    ),
    (
        "ecg",
        "view_ecgfile",
    ),
    (
        "ecg",
        "add_ecgfile",
    ),
)


def grant_bridge_permissions(user):
    for app_label, codename in BRIDGE_PERMISSIONS:
        permission = Permission.objects.get(
            content_type__app_label=app_label,
            codename=codename,
        )
        user.user_permissions.add(permission)


def make_png_upload(
    name="ecg-test.png",
):
    buffer = io.BytesIO()

    image = Image.new(
        "RGB",
        (32, 32),
        "white",
    )

    image.save(
        buffer,
        format="PNG",
    )

    return SimpleUploadedFile(
        name,
        buffer.getvalue(),
        content_type="image/png",
    )


def make_gif_upload(
    name="ecg-test.gif",
):
    buffer = io.BytesIO()

    image = Image.new(
        "RGB",
        (32, 32),
        "white",
    )

    image.save(
        buffer,
        format="GIF",
    )

    return SimpleUploadedFile(
        name,
        buffer.getvalue(),
        content_type="image/gif",
    )


class ECGArchiveBridgeTests(TestCase):
    def setUp(self):
        self.private_media = (
            tempfile.TemporaryDirectory()
        )

        self.settings_override = (
            override_settings(
                PRIVATE_MEDIA_ROOT=(
                    self.private_media.name
                ),
            )
        )

        self.settings_override.enable()

        self.doctor = DoctorFactory()

        self.patient = PatientFactory(
            doctor=self.doctor,
        )

        self.appointment = AppointmentFactory(
            doctor=self.doctor,
            patient=self.patient,
        )

        self.archive = (
            PatientArchive.objects.create(
                patient=self.patient,
                doctor=self.doctor,
                appointment=self.appointment,
                title="ECG Recording",
                notes=(
                    "ECG archive bridge test"
                ),
                archive_type="scan",
                is_critical=False,
                summary_report="",
                status="final",
                created_by=self.doctor.user,
                updated_by=self.doctor.user,
            )
        )

        self.attachment = (
            ArchiveAttachment.objects.create(
                archive=self.archive,
                file=make_png_upload(),
                description=(
                    "ECG test image"
                ),
                uploaded_by=self.doctor.user,
            )
        )

        grant_bridge_permissions(
            self.doctor.user
        )

        self.client.force_login(
            self.doctor.user
        )

        self.url = reverse(
            "ecg:analyze_archive_ecg",
            kwargs={
                "archive_id": (
                    self.archive.pk
                ),
            },
        )

    def tearDown(self):
        self.settings_override.disable()
        self.private_media.cleanup()

    def test_doctor_can_import_archive_ecg_image(
        self,
    ):
        response = self.client.post(
            self.url
        )

        self.assertEqual(
            response.status_code,
            302,
        )

        self.assertEqual(
            ECGRecord.objects.count(),
            1,
        )

        self.assertEqual(
            ECGFile.objects.count(),
            1,
        )

        record = ECGRecord.objects.get()

        ecg_file = ECGFile.objects.get()

        self.assertEqual(
            response.url,
            reverse(
                "ecg:record_detail",
                kwargs={
                    "record_id": record.pk,
                },
            ),
        )

        self.assertEqual(
            record.patient_id,
            self.patient.pk,
        )

        self.assertEqual(
            record.doctor_id,
            self.doctor.pk,
        )

        self.assertEqual(
            record.appointment_id,
            self.appointment.pk,
        )

        self.assertEqual(
            record.hospital_id,
            self.appointment.hospital_id,
        )

        self.assertEqual(
            record.branch_id,
            self.appointment.branch_id,
        )

        self.assertEqual(
            record.department_id,
            self.appointment.department_id,
        )

        self.assertEqual(
            record.created_by_id,
            self.doctor.user_id,
        )

        self.assertEqual(
            record.workflow_status,
            ECGRecord.WorkflowStatus.UPLOADED,
        )

        self.assertEqual(
            record.notes,
            self.archive.notes,
        )

        self.assertEqual(
            ecg_file.record_id,
            record.pk,
        )

        self.assertEqual(
            ecg_file.kind,
            ECGFile.FileKind.IMAGE,
        )

        self.assertEqual(
            ecg_file.source_archive_attachment_id,
            self.attachment.pk,
        )

        self.assertTrue(
            ecg_file.file.name.startswith(
                f"ecg/{record.pk}/"
            )
        )

        self.assertTrue(
            ecg_file.file.storage.exists(
                ecg_file.file.name
            )
        )

        self.assertTrue(
            self.attachment.file.storage.exists(
                self.attachment.file.name
            )
        )

        self.assertNotEqual(
            ecg_file.file.name,
            self.attachment.file.name,
        )

        self.attachment.file.open("rb")

        try:
            source_content = (
                self.attachment.file.read()
            )
        finally:
            self.attachment.file.close()

        ecg_file.file.open("rb")

        try:
            imported_content = (
                ecg_file.file.read()
            )
        finally:
            ecg_file.file.close()

        self.assertEqual(
            imported_content,
            source_content,
        )

    def test_repeated_import_is_idempotent(
        self,
    ):
        first_response = self.client.post(
            self.url
        )

        self.assertEqual(
            first_response.status_code,
            302,
        )

        first_record = (
            ECGRecord.objects.get()
        )

        first_file = ECGFile.objects.get()

        second_response = self.client.post(
            self.url
        )

        self.assertEqual(
            second_response.status_code,
            302,
        )

        self.assertEqual(
            ECGRecord.objects.count(),
            1,
        )

        self.assertEqual(
            ECGFile.objects.count(),
            1,
        )

        second_record = (
            ECGRecord.objects.get()
        )

        second_file = ECGFile.objects.get()

        self.assertEqual(
            second_record.pk,
            first_record.pk,
        )

        self.assertEqual(
            second_file.pk,
            first_file.pk,
        )

        self.assertEqual(
            second_response.url,
            reverse(
                "ecg:record_detail",
                kwargs={
                    "record_id": (
                        first_record.pk
                    ),
                },
            ),
        )

    def test_foreign_doctor_cannot_import_archive(
        self,
    ):
        foreign_doctor = DoctorFactory()

        grant_bridge_permissions(
            foreign_doctor.user
        )

        self.client.force_login(
            foreign_doctor.user
        )

        response = self.client.post(
            self.url
        )

        self.assertEqual(
            response.status_code,
            404,
        )

        self.assertEqual(
            ECGRecord.objects.count(),
            0,
        )

        self.assertEqual(
            ECGFile.objects.count(),
            0,
        )

    def test_non_ecg_archive_is_rejected(
        self,
    ):
        self.archive.title = (
            "Clinical Photo"
        )

        self.archive.save(
            update_fields=[
                "title",
            ]
        )

        response = self.client.post(
            self.url
        )

        self.assertEqual(
            response.status_code,
            404,
        )

        self.assertEqual(
            ECGRecord.objects.count(),
            0,
        )

        self.assertEqual(
            ECGFile.objects.count(),
            0,
        )

    def test_missing_required_permission_gets_403(
        self,
    ):
        permission = Permission.objects.get(
            content_type__app_label="ecg",
            codename="add_ecgfile",
        )

        self.doctor.user.user_permissions.remove(
            permission
        )

        for cache_name in (
            "_perm_cache",
            "_user_perm_cache",
            "_group_perm_cache",
        ):
            if hasattr(
                self.doctor.user,
                cache_name,
            ):
                delattr(
                    self.doctor.user,
                    cache_name,
                )

        response = self.client.post(
            self.url
        )

        self.assertEqual(
            response.status_code,
            403,
        )

        self.assertEqual(
            ECGRecord.objects.count(),
            0,
        )

        self.assertEqual(
            ECGFile.objects.count(),
            0,
        )

    def test_unsupported_archive_file_is_rejected(
        self,
    ):
        self.attachment.delete()

        unsupported_attachment = (
            ArchiveAttachment.objects.create(
                archive=self.archive,
                file=make_gif_upload(),
                description=(
                    "Unsupported ECG GIF"
                ),
                uploaded_by=self.doctor.user,
            )
        )

        response = self.client.post(
            self.url
        )

        self.assertEqual(
            response.status_code,
            302,
        )

        self.assertEqual(
            response.url,
            reverse(
                "medical_archive:archive_detail",
                kwargs={
                    "archive_id": (
                        self.archive.pk
                    ),
                },
            ),
        )

        self.assertEqual(
            ECGRecord.objects.count(),
            0,
        )

        self.assertEqual(
            ECGFile.objects.count(),
            0,
        )

        self.assertTrue(
            ArchiveAttachment.objects.filter(
                pk=unsupported_attachment.pk
            ).exists()
        )

    def test_analyze_endpoint_requires_post(
        self,
    ):
        response = self.client.get(
            self.url
        )

        self.assertEqual(
            response.status_code,
            405,
        )

        self.assertEqual(
            ECGRecord.objects.count(),
            0,
        )

        self.assertEqual(
            ECGFile.objects.count(),
            0,
        )

    def test_imported_record_is_visible_to_doctor(
        self,
    ):
        import_response = self.client.post(
            self.url
        )

        self.assertEqual(
            import_response.status_code,
            302,
        )

        record = ECGRecord.objects.get()

        detail_response = self.client.get(
            reverse(
                "ecg:record_detail",
                kwargs={
                    "record_id": record.pk,
                },
            )
        )

        self.assertEqual(
            detail_response.status_code,
            200,
        )

        self.assertEqual(
            detail_response.context[
                "record"
            ].pk,
            record.pk,
        )

    def test_source_attachment_deletion_keeps_ecg_copy(
        self,
    ):
        response = self.client.post(
            self.url
        )

        self.assertEqual(
            response.status_code,
            302,
        )

        ecg_file = ECGFile.objects.get()

        imported_file_name = (
            ecg_file.file.name
        )

        imported_storage = (
            ecg_file.file.storage
        )

        self.assertTrue(
            imported_storage.exists(
                imported_file_name
            )
        )

        self.attachment.delete()

        ecg_file.refresh_from_db()

        self.assertIsNone(
            ecg_file.source_archive_attachment_id
        )

        self.assertTrue(
            ECGRecord.objects.filter(
                pk=ecg_file.record_id
            ).exists()
        )

        self.assertTrue(
            ECGFile.objects.filter(
                pk=ecg_file.pk
            ).exists()
        )

        self.assertTrue(
            imported_storage.exists(
                imported_file_name
            )
        )