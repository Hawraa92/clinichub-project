import io
import tempfile

from PIL import Image

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings

from appointments.tests.factories import AppointmentFactory
from ecg.models import ECGFile, ECGRecord
from ecg.services.image_pipeline import (
    ECGImagePipelineError,
    run_ecg_image_pipeline,
)


class ECGImagePipelineTests(TestCase):
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
        )

    def tearDown(self):
        self.settings_override.disable()
        self.private_media.cleanup()

    def create_trace_png_bytes(self):
        width = 20
        height = 12

        image = Image.new(
            "RGB",
            (width, height),
            color=(
                255,
                255,
                255,
            ),
        )

        trace_rows = [
            6,
            5,
            4,
            5,
            6,
            7,
            6,
            5,
            4,
            5,
            6,
            7,
            6,
            5,
            4,
            5,
            6,
            7,
            6,
            5,
        ]

        for x_position, y_position in enumerate(
            trace_rows
        ):
            image.putpixel(
                (
                    x_position,
                    y_position,
                ),
                (
                    0,
                    0,
                    0,
                ),
            )

        buffer = io.BytesIO()

        image.save(
            buffer,
            format="PNG",
        )

        return buffer.getvalue()

    def create_blank_png_bytes(self):
        image = Image.new(
            "RGB",
            (
                20,
                12,
            ),
            color=(
                255,
                255,
                255,
            ),
        )

        buffer = io.BytesIO()

        image.save(
            buffer,
            format="PNG",
        )

        return buffer.getvalue()

    def create_image_file(
        self,
        content,
        filename="ecg.png",
    ):
        return ECGFile.objects.create(
            record=self.record,
            kind=ECGFile.FileKind.IMAGE,
            file=SimpleUploadedFile(
                filename,
                content,
                content_type="image/png",
            ),
        )

    def test_pipeline_reconstructs_signal_from_ecg_image(self):
        ecg_file = self.create_image_file(
            self.create_trace_png_bytes()
        )

        result = run_ecg_image_pipeline(
            ecg_file
        )

        self.assertEqual(
            result.width,
            20,
        )

        self.assertEqual(
            result.height,
            12,
        )

        self.assertEqual(
            result.reconstructed_signal.sample_count,
            20,
        )

        self.assertEqual(
            result.reconstructed_signal.missing_count,
            0,
        )

        self.assertEqual(
            result.coverage_ratio,
            1.0,
        )

        self.assertEqual(
            len(
                result.signal_values
            ),
            20,
        )

        self.assertEqual(
            result.x_positions,
            tuple(
                range(20)
            ),
        )

    def test_pipeline_exposes_each_processing_stage(self):
        ecg_file = self.create_image_file(
            self.create_trace_png_bytes()
        )

        result = run_ecg_image_pipeline(
            ecg_file
        )

        self.assertEqual(
            result.processed_image.width,
            20,
        )

        self.assertEqual(
            result.trace_candidates.width,
            20,
        )

        self.assertEqual(
            result.reconstructed_signal.width,
            20,
        )

        self.assertGreater(
            result.trace_candidates.candidate_pixel_count,
            0,
        )

        self.assertGreater(
            result.reconstructed_signal.sample_count,
            0,
        )

    def test_invalid_image_is_wrapped_as_pipeline_error(self):
        ecg_file = self.create_image_file(
            b"This is not a real image."
        )

        with self.assertRaises(
            ECGImagePipelineError
        ):
            run_ecg_image_pipeline(
                ecg_file
            )

    def test_blank_image_is_wrapped_as_pipeline_error(self):
        ecg_file = self.create_image_file(
            self.create_blank_png_bytes()
        )

        with self.assertRaises(
            ECGImagePipelineError
        ):
            run_ecg_image_pipeline(
                ecg_file
            )

    def test_pipeline_rejects_region_without_trace(self):
        ecg_file = self.create_image_file(
            self.create_trace_png_bytes()
        )

        with self.assertRaises(
            ECGImagePipelineError
        ):
            run_ecg_image_pipeline(
                ecg_file,
                region_top=0,
                region_bottom=3,
            )