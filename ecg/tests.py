import tempfile

from django.contrib.auth.models import Permission
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from appointments.tests.factories import (
    AppointmentFactory,
    BranchFactory,
    DepartmentFactory,
    DoctorFactory,
    HospitalFactory,
    PatientFactory,
    UserFactory,
)
from ecg.models import ECGFile, ECGRecord


def grant_add_ecg_permission(user):
    permission = Permission.objects.get(
        content_type__app_label="ecg",
        codename="add_ecgrecord",
    )
    user.user_permissions.add(permission)


def grant_view_ecg_permission(user):
    permission = Permission.objects.get(
        content_type__app_label="ecg",
        codename="view_ecgrecord",
    )
    user.user_permissions.add(permission)


def grant_add_ecg_file_permission(user):
    permission = Permission.objects.get(
        content_type__app_label="ecg",
        codename="add_ecgfile",
    )
    user.user_permissions.add(permission)


def grant_view_ecg_file_permission(user):
    permission = Permission.objects.get(
        content_type__app_label="ecg",
        codename="view_ecgfile",
    )
    user.user_permissions.add(permission)


class ECGRecordValidationTests(TestCase):
    def test_valid_record_matches_appointment(self):
        appointment = AppointmentFactory()

        record = ECGRecord(
            patient=appointment.patient,
            doctor=appointment.doctor,
            appointment=appointment,
            hospital=appointment.hospital,
            branch=appointment.branch,
            department=appointment.department,
        )

        record.full_clean()

    def test_rejects_patient_different_from_appointment(self):
        appointment = AppointmentFactory()
        other_patient = PatientFactory()

        record = ECGRecord(
            patient=other_patient,
            doctor=appointment.doctor,
            appointment=appointment,
            hospital=appointment.hospital,
            branch=appointment.branch,
            department=appointment.department,
        )

        with self.assertRaises(ValidationError) as context:
            record.full_clean()

        self.assertIn(
            "patient",
            context.exception.message_dict,
        )

    def test_rejects_doctor_different_from_appointment(self):
        appointment = AppointmentFactory()
        other_appointment = AppointmentFactory()

        record = ECGRecord(
            patient=appointment.patient,
            doctor=other_appointment.doctor,
            appointment=appointment,
            hospital=appointment.hospital,
            branch=appointment.branch,
            department=appointment.department,
        )

        with self.assertRaises(ValidationError) as context:
            record.full_clean()

        self.assertIn(
            "doctor",
            context.exception.message_dict,
        )

    def test_rejects_location_different_from_appointment(self):
        appointment = AppointmentFactory()

        other_hospital = HospitalFactory(
            code="ECG-OTHER-HOSPITAL",
            name="ECG Other Hospital",
        )
        other_branch = BranchFactory(
            hospital=other_hospital,
            code="ECG-OTHER-BRANCH",
            name="ECG Other Branch",
        )
        other_department = DepartmentFactory(
            branch=other_branch,
            code="ECG-OTHER-DEPARTMENT",
            name="ECG Other Department",
        )

        record = ECGRecord(
            patient=appointment.patient,
            doctor=appointment.doctor,
            appointment=appointment,
            hospital=other_hospital,
            branch=other_branch,
            department=other_department,
        )

        with self.assertRaises(ValidationError) as context:
            record.full_clean()

        errors = context.exception.message_dict

        self.assertTrue(
            any(
                field in errors
                for field in (
                    "hospital",
                    "branch",
                    "department",
                )
            )
        )


class ECGCreateRecordSecurityTests(TestCase):
    def setUp(self):
        self.url = reverse("ecg:create_record")

    def test_anonymous_user_is_redirected_to_login(self):
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 302)
        self.assertIn(
            "/accounts/login/",
            response.url,
        )

    def test_user_without_add_permission_gets_403(self):
        doctor = DoctorFactory()

        self.client.force_login(doctor.user)

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 403)

    def test_doctor_form_is_scoped_to_own_data(self):
        doctor = DoctorFactory()
        foreign_doctor = DoctorFactory()

        own_patient = PatientFactory(
            doctor=doctor,
        )
        foreign_patient = PatientFactory(
            doctor=foreign_doctor,
        )

        own_appointment = AppointmentFactory(
            doctor=doctor,
            patient=own_patient,
        )
        foreign_appointment = AppointmentFactory(
            doctor=foreign_doctor,
            patient=foreign_patient,
        )

        grant_add_ecg_permission(doctor.user)
        self.client.force_login(doctor.user)

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)

        form = response.context["form"]

        self.assertEqual(
            set(
                form.fields["doctor"]
                .queryset
                .values_list("pk", flat=True)
            ),
            {doctor.pk},
        )

        self.assertIn(
            own_patient.pk,
            set(
                form.fields["patient"]
                .queryset
                .values_list("pk", flat=True)
            ),
        )

        self.assertNotIn(
            foreign_patient.pk,
            set(
                form.fields["patient"]
                .queryset
                .values_list("pk", flat=True)
            ),
        )

        appointment_ids = set(
            form.fields["appointment"]
            .queryset
            .values_list("pk", flat=True)
        )

        self.assertIn(
            own_appointment.pk,
            appointment_ids,
        )

        self.assertNotIn(
            foreign_appointment.pk,
            appointment_ids,
        )

    def test_secretary_form_is_scoped_to_assigned_doctor(self):
        doctor = DoctorFactory()
        foreign_doctor = DoctorFactory()

        secretary = UserFactory(
            role="secretary",
            assigned_doctor=doctor,
        )

        own_patient = PatientFactory(
            doctor=doctor,
        )
        foreign_patient = PatientFactory(
            doctor=foreign_doctor,
        )

        own_appointment = AppointmentFactory(
            doctor=doctor,
            patient=own_patient,
        )
        foreign_appointment = AppointmentFactory(
            doctor=foreign_doctor,
            patient=foreign_patient,
        )

        grant_add_ecg_permission(secretary)
        self.client.force_login(secretary)

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)

        form = response.context["form"]

        self.assertEqual(
            set(
                form.fields["doctor"]
                .queryset
                .values_list("pk", flat=True)
            ),
            {doctor.pk},
        )

        patient_ids = set(
            form.fields["patient"]
            .queryset
            .values_list("pk", flat=True)
        )

        self.assertIn(
            own_patient.pk,
            patient_ids,
        )

        self.assertNotIn(
            foreign_patient.pk,
            patient_ids,
        )

        appointment_ids = set(
            form.fields["appointment"]
            .queryset
            .values_list("pk", flat=True)
        )

        self.assertIn(
            own_appointment.pk,
            appointment_ids,
        )

        self.assertNotIn(
            foreign_appointment.pk,
            appointment_ids,
        )

    def test_valid_post_creates_ecg_record(self):
        doctor = DoctorFactory()

        patient = PatientFactory(
            doctor=doctor,
        )

        appointment = AppointmentFactory(
            doctor=doctor,
            patient=patient,
        )

        grant_add_ecg_permission(doctor.user)
        self.client.force_login(doctor.user)

        recorded_at = timezone.localtime(
            timezone.now()
        ).strftime(
            "%Y-%m-%dT%H:%M"
        )

        response = self.client.post(
            self.url,
            {
                "patient": patient.pk,
                "doctor": doctor.pk,
                "appointment": appointment.pk,
                "hospital": appointment.hospital_id,
                "branch": appointment.branch_id,
                "department": appointment.department_id,
                "recorded_at": recorded_at,
                "device_manufacturer": "Test Manufacturer",
                "device_model": "Test ECG Device",
                "sampling_frequency_hz": 500,
                "lead_count": 12,
                "duration_seconds": "10.00",
                "notes": "Test ECG record",
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            ECGRecord.objects.count(),
            1,
        )

        record = ECGRecord.objects.get()

        self.assertEqual(
            record.patient_id,
            patient.pk,
        )
        self.assertEqual(
            record.doctor_id,
            doctor.pk,
        )
        self.assertEqual(
            record.appointment_id,
            appointment.pk,
        )
        self.assertEqual(
            record.created_by_id,
            doctor.user_id,
        )

    def test_foreign_appointment_post_is_rejected(self):
        doctor = DoctorFactory()
        foreign_doctor = DoctorFactory()

        patient = PatientFactory(
            doctor=doctor,
        )
        foreign_patient = PatientFactory(
            doctor=foreign_doctor,
        )

        appointment = AppointmentFactory(
            doctor=doctor,
            patient=patient,
        )
        foreign_appointment = AppointmentFactory(
            doctor=foreign_doctor,
            patient=foreign_patient,
        )

        grant_add_ecg_permission(doctor.user)
        self.client.force_login(doctor.user)

        recorded_at = timezone.localtime(
            timezone.now()
        ).strftime(
            "%Y-%m-%dT%H:%M"
        )

        response = self.client.post(
            self.url,
            {
                "patient": patient.pk,
                "doctor": doctor.pk,
                "appointment": foreign_appointment.pk,
                "hospital": appointment.hospital_id,
                "branch": appointment.branch_id,
                "department": appointment.department_id,
                "recorded_at": recorded_at,
                "device_manufacturer": "Test Manufacturer",
                "device_model": "Test ECG Device",
                "sampling_frequency_hz": 500,
                "lead_count": 12,
                "duration_seconds": "10.00",
                "notes": "Spoofed ECG attempt",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            ECGRecord.objects.count(),
            0,
        )

        form = response.context["form"]

        self.assertIn(
            "appointment",
            form.errors,
        )


class ECGDashboardSecurityTests(TestCase):
    def setUp(self):
        self.url = reverse("ecg:dashboard")

    def test_user_without_view_permission_gets_403(self):
        doctor = DoctorFactory()

        self.client.force_login(doctor.user)

        response = self.client.get(self.url)

        self.assertEqual(
            response.status_code,
            403,
        )

    def test_doctor_dashboard_shows_only_own_records(self):
        doctor = DoctorFactory()
        foreign_doctor = DoctorFactory()

        patient = PatientFactory(
            doctor=doctor,
        )
        foreign_patient = PatientFactory(
            doctor=foreign_doctor,
        )

        appointment = AppointmentFactory(
            doctor=doctor,
            patient=patient,
        )
        foreign_appointment = AppointmentFactory(
            doctor=foreign_doctor,
            patient=foreign_patient,
        )

        own_record = ECGRecord.objects.create(
            patient=patient,
            doctor=doctor,
            appointment=appointment,
            hospital=appointment.hospital,
            branch=appointment.branch,
            department=appointment.department,
        )

        foreign_record = ECGRecord.objects.create(
            patient=foreign_patient,
            doctor=foreign_doctor,
            appointment=foreign_appointment,
            hospital=foreign_appointment.hospital,
            branch=foreign_appointment.branch,
            department=foreign_appointment.department,
        )

        grant_view_ecg_permission(
            doctor.user
        )
        self.client.force_login(
            doctor.user
        )

        response = self.client.get(
            self.url
        )

        self.assertEqual(
            response.status_code,
            200,
        )

        record_ids = {
            record.pk
            for record in response.context["records"]
        }

        self.assertIn(
            own_record.pk,
            record_ids,
        )

        self.assertNotIn(
            foreign_record.pk,
            record_ids,
        )

    def test_secretary_dashboard_is_scoped_to_assigned_doctor(self):
        doctor = DoctorFactory()
        foreign_doctor = DoctorFactory()

        secretary = UserFactory(
            role="secretary",
            assigned_doctor=doctor,
        )

        patient = PatientFactory(
            doctor=doctor,
        )
        foreign_patient = PatientFactory(
            doctor=foreign_doctor,
        )

        appointment = AppointmentFactory(
            doctor=doctor,
            patient=patient,
        )
        foreign_appointment = AppointmentFactory(
            doctor=foreign_doctor,
            patient=foreign_patient,
        )

        own_record = ECGRecord.objects.create(
            patient=patient,
            doctor=doctor,
            appointment=appointment,
            hospital=appointment.hospital,
            branch=appointment.branch,
            department=appointment.department,
        )

        foreign_record = ECGRecord.objects.create(
            patient=foreign_patient,
            doctor=foreign_doctor,
            appointment=foreign_appointment,
            hospital=foreign_appointment.hospital,
            branch=foreign_appointment.branch,
            department=foreign_appointment.department,
        )

        grant_view_ecg_permission(
            secretary
        )
        self.client.force_login(
            secretary
        )

        response = self.client.get(
            self.url
        )

        self.assertEqual(
            response.status_code,
            200,
        )

        record_ids = {
            record.pk
            for record in response.context["records"]
        }

        self.assertIn(
            own_record.pk,
            record_ids,
        )

        self.assertNotIn(
            foreign_record.pk,
            record_ids,
        )


class ECGRecordDetailSecurityTests(TestCase):
    def test_authorized_doctor_can_view_own_record(self):
        doctor = DoctorFactory()

        patient = PatientFactory(
            doctor=doctor,
        )

        appointment = AppointmentFactory(
            doctor=doctor,
            patient=patient,
        )

        record = ECGRecord.objects.create(
            patient=patient,
            doctor=doctor,
            appointment=appointment,
            hospital=appointment.hospital,
            branch=appointment.branch,
            department=appointment.department,
        )

        grant_view_ecg_permission(
            doctor.user
        )
        self.client.force_login(
            doctor.user
        )

        response = self.client.get(
            reverse(
                "ecg:record_detail",
                kwargs={
                    "record_id": record.pk,
                },
            )
        )

        self.assertEqual(
            response.status_code,
            200,
        )

        self.assertEqual(
            response.context["record"].pk,
            record.pk,
        )

    def test_doctor_cannot_view_foreign_record_by_id(self):
        doctor = DoctorFactory()
        foreign_doctor = DoctorFactory()

        foreign_patient = PatientFactory(
            doctor=foreign_doctor,
        )

        foreign_appointment = AppointmentFactory(
            doctor=foreign_doctor,
            patient=foreign_patient,
        )

        foreign_record = ECGRecord.objects.create(
            patient=foreign_patient,
            doctor=foreign_doctor,
            appointment=foreign_appointment,
            hospital=foreign_appointment.hospital,
            branch=foreign_appointment.branch,
            department=foreign_appointment.department,
        )

        grant_view_ecg_permission(
            doctor.user
        )
        self.client.force_login(
            doctor.user
        )

        response = self.client.get(
            reverse(
                "ecg:record_detail",
                kwargs={
                    "record_id": foreign_record.pk,
                },
            )
        )

        self.assertEqual(
            response.status_code,
            404,
        )

class ECGFileUploadSecurityTests(TestCase):
    def setUp(self):
        self.private_media = tempfile.TemporaryDirectory()
        self.settings_override = override_settings(
            PRIVATE_MEDIA_ROOT=self.private_media.name,
        )
        self.settings_override.enable()

    def tearDown(self):
        self.settings_override.disable()
        self.private_media.cleanup()

    def test_user_without_add_file_permission_gets_403(self):
        doctor = DoctorFactory()

        patient = PatientFactory(
            doctor=doctor,
        )

        appointment = AppointmentFactory(
            doctor=doctor,
            patient=patient,
        )

        record = ECGRecord.objects.create(
            patient=patient,
            doctor=doctor,
            appointment=appointment,
            hospital=appointment.hospital,
            branch=appointment.branch,
            department=appointment.department,
        )

        grant_view_ecg_permission(
            doctor.user
        )
        self.client.force_login(
            doctor.user
        )

        response = self.client.get(
            reverse(
                "ecg:upload_file",
                kwargs={
                    "record_id": record.pk,
                },
            )
        )

        self.assertEqual(
            response.status_code,
            403,
        )

    def test_doctor_cannot_upload_to_foreign_record_by_id(self):
        doctor = DoctorFactory()
        foreign_doctor = DoctorFactory()

        foreign_patient = PatientFactory(
            doctor=foreign_doctor,
        )

        foreign_appointment = AppointmentFactory(
            doctor=foreign_doctor,
            patient=foreign_patient,
        )

        foreign_record = ECGRecord.objects.create(
            patient=foreign_patient,
            doctor=foreign_doctor,
            appointment=foreign_appointment,
            hospital=foreign_appointment.hospital,
            branch=foreign_appointment.branch,
            department=foreign_appointment.department,
        )

        grant_view_ecg_permission(
            doctor.user
        )
        grant_add_ecg_file_permission(
            doctor.user
        )
        self.client.force_login(
            doctor.user
        )

        test_file = SimpleUploadedFile(
            "foreign.csv",
            b"time,value\n0,1\n",
            content_type="text/csv",
        )

        response = self.client.post(
            reverse(
                "ecg:upload_file",
                kwargs={
                    "record_id": foreign_record.pk,
                },
            ),
            {
                "kind": ECGFile.FileKind.CSV,
                "file": test_file,
            },
        )

        self.assertEqual(
            response.status_code,
            404,
        )
        self.assertEqual(
            ECGFile.objects.count(),
            0,
        )

    def test_valid_upload_creates_private_ecg_file_for_record(self):
        doctor = DoctorFactory()

        patient = PatientFactory(
            doctor=doctor,
        )

        appointment = AppointmentFactory(
            doctor=doctor,
            patient=patient,
        )

        record = ECGRecord.objects.create(
            patient=patient,
            doctor=doctor,
            appointment=appointment,
            hospital=appointment.hospital,
            branch=appointment.branch,
            department=appointment.department,
        )

        grant_view_ecg_permission(
            doctor.user
        )
        grant_add_ecg_file_permission(
            doctor.user
        )
        self.client.force_login(
            doctor.user
        )

        test_file = SimpleUploadedFile(
            "sample.csv",
            b"time,value\n0,1\n",
            content_type="text/csv",
        )

        response = self.client.post(
            reverse(
                "ecg:upload_file",
                kwargs={
                    "record_id": record.pk,
                },
            ),
            {
                "kind": ECGFile.FileKind.CSV,
                "file": test_file,
            },
        )

        self.assertEqual(
            response.status_code,
            302,
        )
        self.assertEqual(
            ECGFile.objects.count(),
            1,
        )

        ecg_file = ECGFile.objects.get()

        self.assertEqual(
            ecg_file.record_id,
            record.pk,
        )
        self.assertEqual(
            ecg_file.kind,
            ECGFile.FileKind.CSV,
        )
        self.assertTrue(
            ecg_file.file.name.startswith(
                f"ecg/{record.pk}/"
            )
        )
        self.assertTrue(
            ecg_file.file.name.endswith(
                ".csv"
            )
        )
        self.assertTrue(
            ecg_file.file.storage.exists(
                ecg_file.file.name
            )
        )

    def test_mismatched_extension_is_rejected(self):
        doctor = DoctorFactory()

        patient = PatientFactory(
            doctor=doctor,
        )

        appointment = AppointmentFactory(
            doctor=doctor,
            patient=patient,
        )

        record = ECGRecord.objects.create(
            patient=patient,
            doctor=doctor,
            appointment=appointment,
            hospital=appointment.hospital,
            branch=appointment.branch,
            department=appointment.department,
        )

        grant_view_ecg_permission(
            doctor.user
        )
        grant_add_ecg_file_permission(
            doctor.user
        )
        self.client.force_login(
            doctor.user
        )

        test_file = SimpleUploadedFile(
            "not-a-report.csv",
            b"time,value\n0,1\n",
            content_type="text/csv",
        )

        response = self.client.post(
            reverse(
                "ecg:upload_file",
                kwargs={
                    "record_id": record.pk,
                },
            ),
            {
                "kind": ECGFile.FileKind.REPORT_PDF,
                "file": test_file,
            },
        )

        self.assertEqual(
            response.status_code,
            200,
        )
        self.assertEqual(
            ECGFile.objects.count(),
            0,
        )
        self.assertIn(
            "file",
            response.context["form"].errors,
        )

class ECGFileDownloadSecurityTests(TestCase):
    def setUp(self):
        self.private_media = tempfile.TemporaryDirectory()

        self.settings_override = override_settings(
            PRIVATE_MEDIA_ROOT=self.private_media.name,
        )
        self.settings_override.enable()

    def tearDown(self):
        self.settings_override.disable()
        self.private_media.cleanup()

    def test_user_without_view_file_permission_gets_403(self):
        doctor = DoctorFactory()

        patient = PatientFactory(
            doctor=doctor,
        )

        appointment = AppointmentFactory(
            doctor=doctor,
            patient=patient,
        )

        record = ECGRecord.objects.create(
            patient=patient,
            doctor=doctor,
            appointment=appointment,
            hospital=appointment.hospital,
            branch=appointment.branch,
            department=appointment.department,
        )

        ecg_file = ECGFile.objects.create(
            record=record,
            kind=ECGFile.FileKind.CSV,
            file=SimpleUploadedFile(
                "sample.csv",
                b"time,value\n0,1\n",
                content_type="text/csv",
            ),
        )

        grant_view_ecg_permission(
            doctor.user
        )

        self.client.force_login(
            doctor.user
        )

        response = self.client.get(
            reverse(
                "ecg:download_file",
                kwargs={
                    "record_id": record.pk,
                    "file_id": ecg_file.pk,
                },
            )
        )

        self.assertEqual(
            response.status_code,
            403,
        )

    def test_doctor_cannot_download_foreign_file_by_id(self):
        doctor = DoctorFactory()
        foreign_doctor = DoctorFactory()

        foreign_patient = PatientFactory(
            doctor=foreign_doctor,
        )

        foreign_appointment = AppointmentFactory(
            doctor=foreign_doctor,
            patient=foreign_patient,
        )

        foreign_record = ECGRecord.objects.create(
            patient=foreign_patient,
            doctor=foreign_doctor,
            appointment=foreign_appointment,
            hospital=foreign_appointment.hospital,
            branch=foreign_appointment.branch,
            department=foreign_appointment.department,
        )

        foreign_file = ECGFile.objects.create(
            record=foreign_record,
            kind=ECGFile.FileKind.CSV,
            file=SimpleUploadedFile(
                "foreign.csv",
                b"time,value\n0,99\n",
                content_type="text/csv",
            ),
        )

        grant_view_ecg_permission(
            doctor.user
        )

        grant_view_ecg_file_permission(
            doctor.user
        )

        self.client.force_login(
            doctor.user
        )

        response = self.client.get(
            reverse(
                "ecg:download_file",
                kwargs={
                    "record_id": foreign_record.pk,
                    "file_id": foreign_file.pk,
                },
            )
        )

        self.assertEqual(
            response.status_code,
            404,
        )

    def test_authorized_download_returns_private_attachment(self):
        doctor = DoctorFactory()

        patient = PatientFactory(
            doctor=doctor,
        )

        appointment = AppointmentFactory(
            doctor=doctor,
            patient=patient,
        )

        record = ECGRecord.objects.create(
            patient=patient,
            doctor=doctor,
            appointment=appointment,
            hospital=appointment.hospital,
            branch=appointment.branch,
            department=appointment.department,
        )

        file_content = b"time,value\n0,1\n1,2\n"

        ecg_file = ECGFile.objects.create(
            record=record,
            kind=ECGFile.FileKind.CSV,
            file=SimpleUploadedFile(
                "sample.csv",
                file_content,
                content_type="text/csv",
            ),
        )

        grant_view_ecg_permission(
            doctor.user
        )

        grant_view_ecg_file_permission(
            doctor.user
        )

        self.client.force_login(
            doctor.user
        )

        response = self.client.get(
            reverse(
                "ecg:download_file",
                kwargs={
                    "record_id": record.pk,
                    "file_id": ecg_file.pk,
                },
            )
        )

        self.assertEqual(
            response.status_code,
            200,
        )

        self.assertEqual(
            response["Content-Type"],
            "application/octet-stream",
        )

        self.assertEqual(
            response["Cache-Control"],
            "private, no-store",
        )

        self.assertEqual(
            response["Pragma"],
            "no-cache",
        )

        self.assertEqual(
            response["X-Content-Type-Options"],
            "nosniff",
        )

        self.assertIn(
            "attachment;",
            response["Content-Disposition"],
        )

        self.assertIn(
            f"ecg-record-{record.pk}-file-{ecg_file.pk}.csv",
            response["Content-Disposition"],
        )

        downloaded_content = b"".join(
            response.streaming_content
        )

        self.assertEqual(
            downloaded_content,
            file_content,
        )
