import tempfile

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings

from appointments.tests.factories import AppointmentFactory
from ecg.models import ECGFile, ECGRecord
from ecg.services.parser import (
    ECGParseError,
    parse_csv_ecg,
)


class ECGCSVParserTests(TestCase):
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

    def tearDown(self):
        self.settings_override.disable()
        self.private_media.cleanup()

    def create_csv_file(
        self,
        content,
        filename="ecg.csv",
    ):
        return ECGFile.objects.create(
            record=self.record,
            kind=ECGFile.FileKind.CSV,
            file=SimpleUploadedFile(
                filename,
                content,
                content_type="text/csv",
            ),
        )

    def test_valid_csv_is_parsed(self):
        ecg_file = self.create_csv_file(
            (
                b"time,lead_I,lead_II\n"
                b"0.000,0.10,0.20\n"
                b"0.002,0.15,0.25\n"
                b"0.004,0.12,0.22\n"
            )
        )

        parsed = parse_csv_ecg(
            ecg_file
        )

        self.assertEqual(
            parsed.source_format,
            "csv",
        )

        self.assertEqual(
            parsed.headers,
            (
                "time",
                "lead_I",
                "lead_II",
            ),
        )

        self.assertEqual(
            parsed.signal_names,
            (
                "lead_I",
                "lead_II",
            ),
        )

        self.assertEqual(
            parsed.row_count,
            3,
        )

        self.assertEqual(
            parsed.lead_count,
            2,
        )

        self.assertEqual(
            parsed.time_values,
            (
                0.0,
                0.002,
                0.004,
            ),
        )

        self.assertEqual(
            parsed.signals["lead_I"],
            (
                0.10,
                0.15,
                0.12,
            ),
        )

        self.assertEqual(
            parsed.signals["lead_II"],
            (
                0.20,
                0.25,
                0.22,
            ),
        )

        self.assertEqual(
            parsed.sampling_frequency_hz,
            500.0,
        )

        self.assertAlmostEqual(
            parsed.duration_seconds,
            0.004,
        )

    def test_non_numeric_signal_value_is_rejected(self):
        ecg_file = self.create_csv_file(
            (
                b"time,lead_I,lead_II\n"
                b"0.000,0.10,0.20\n"
                b"0.002,invalid,0.25\n"
            )
        )

        with self.assertRaises(
            ECGParseError
        ):
            parse_csv_ecg(
                ecg_file
            )

    def test_non_increasing_time_is_rejected(self):
        ecg_file = self.create_csv_file(
            (
                b"time,lead_I,lead_II\n"
                b"0.000,0.10,0.20\n"
                b"0.002,0.15,0.25\n"
                b"0.002,0.12,0.22\n"
            )
        )

        with self.assertRaises(
            ECGParseError
        ):
            parse_csv_ecg(
                ecg_file
            )

    def test_row_with_wrong_column_count_is_rejected(self):
        ecg_file = self.create_csv_file(
            (
                b"time,lead_I,lead_II\n"
                b"0.000,0.10,0.20\n"
                b"0.002,0.15\n"
            )
        )

        with self.assertRaises(
            ECGParseError
        ):
            parse_csv_ecg(
                ecg_file
            )