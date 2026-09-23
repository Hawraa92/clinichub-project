import tempfile
from unittest.mock import patch

from django.contrib.auth.models import Permission
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from appointments.tests.factories import AppointmentFactory
from ecg.models import ECGFile, ECGRecord


class ECGWaveformViewTests(TestCase):
    def setUp(self):
        self.private_media = tempfile.TemporaryDirectory()

        self.settings_override = override_settings(
            PRIVATE_MEDIA_ROOT=self.private_media.name,
        )
        self.settings_override.enable()

        self.appointment = AppointmentFactory()

        self.record = ECGRecord.objects.create(
            patient=self.appointment.patient,
            doctor=self.appointment.doctor,
            appointment=self.appointment,
            hospital=self.appointment.hospital,
            branch=self.appointment.branch,
            department=self.appointment.department,
            sampling_frequency_hz=500,
        )

        self.user = self.appointment.doctor.user

        self.grant_permission(
            "view_ecgrecord"
        )

        self.detail_url = reverse(
            "ecg:record_detail",
            kwargs={
                "record_id": self.record.pk,
            },
        )

    def tearDown(self):
        self.settings_override.disable()
        self.private_media.cleanup()

    def grant_permission(self, codename):
        permission = Permission.objects.get(
            content_type__app_label="ecg",
            codename=codename,
        )

        self.user.user_permissions.add(
            permission
        )

    def login(self):
        self.client.force_login(
            self.user
        )

    def create_csv_file(
        self,
        content=None,
    ):
        if content is None:
            content = (
                b"time,lead_I,lead_II\n"
                b"0.000,0.10,0.20\n"
                b"0.002,0.15,0.25\n"
                b"0.004,0.12,0.22\n"
            )

        return ECGFile.objects.create(
            record=self.record,
            kind=ECGFile.FileKind.CSV,
            file=SimpleUploadedFile(
                "ecg.csv",
                content,
                content_type="text/csv",
            ),
        )

    def test_authorized_user_sees_waveform_preview(self):
        self.grant_permission(
            "view_ecgfile"
        )

        self.create_csv_file()

        self.login()

        response = self.client.get(
            self.detail_url
        )

        self.assertEqual(
            response.status_code,
            200,
        )

        self.assertIsNotNone(
            response.context[
                "waveform_preview"
            ]
        )

        self.assertIsNotNone(
            response.context[
                "waveform_chart_data"
            ]
        )

        self.assertFalse(
            response.context[
                "waveform_error"
            ]
        )

        self.assertContains(
            response,
            'id="ecg-waveform-data"',
        )

        self.assertContains(
            response,
            "ECG Waveform Preview",
        )

        self.assertContains(
            response,
            "Preview only:",
        )

    def test_user_without_file_permission_does_not_parse_waveform(self):
        self.create_csv_file()

        self.login()

        with patch(
            "ecg.views.parse_csv_ecg"
        ) as mocked_parser:
            response = self.client.get(
                self.detail_url
            )

        self.assertEqual(
            response.status_code,
            200,
        )

        mocked_parser.assert_not_called()

        self.assertIsNone(
            response.context[
                "waveform_preview"
            ]
        )

        self.assertIsNone(
            response.context[
                "waveform_chart_data"
            ]
        )

        self.assertIsNone(
            response.context[
                "waveform_file"
            ]
        )

        self.assertNotContains(
            response,
            'id="ecg-waveform-data"',
        )

    def test_invalid_csv_does_not_break_record_page(self):
        self.grant_permission(
            "view_ecgfile"
        )

        self.create_csv_file(
            content=(
                b"time,lead_I\n"
                b"0.000,0.10\n"
                b"0.002,invalid\n"
            )
        )

        self.login()

        response = self.client.get(
            self.detail_url
        )

        self.assertEqual(
            response.status_code,
            200,
        )

        self.assertTrue(
            response.context[
                "waveform_error"
            ]
        )

        self.assertIsNone(
            response.context[
                "waveform_preview"
            ]
        )

        self.assertIsNone(
            response.context[
                "waveform_chart_data"
            ]
        )

        self.assertContains(
            response,
            "The ECG CSV file could not be prepared for waveform",
        )

        self.assertNotContains(
            response,
            'id="ecg-waveform-data"',
        )

    def test_record_without_csv_has_no_waveform_preview(self):
        self.grant_permission(
            "view_ecgfile"
        )

        self.login()

        response = self.client.get(
            self.detail_url
        )

        self.assertEqual(
            response.status_code,
            200,
        )

        self.assertIsNone(
            response.context[
                "waveform_preview"
            ]
        )

        self.assertIsNone(
            response.context[
                "waveform_chart_data"
            ]
        )

        self.assertIsNone(
            response.context[
                "waveform_file"
            ]
        )

        self.assertFalse(
            response.context[
                "waveform_error"
            ]
        )

        self.assertContains(
            response,
            "No supported ECG CSV signal file is available for",
        )

        self.assertNotContains(
            response,
            'id="ecg-waveform-data"',
        )