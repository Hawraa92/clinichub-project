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
from ecg.services.perspective import (
    ECGImageQuadrilateral,
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

    def create_two_region_trace_png_bytes(self):
        width = 20
        height = 24

        image = Image.new(
            "RGB",
            (width, height),
            color=(
                255,
                255,
                255,
            ),
        )

        first_trace_rows = [
            5,
            4,
            3,
            4,
            5,
            6,
            5,
            4,
            3,
            4,
            5,
            6,
            5,
            4,
            3,
            4,
            5,
            6,
            5,
            4,
        ]

        second_trace_rows = [
            18,
            17,
            16,
            17,
            18,
            19,
            18,
            17,
            16,
            17,
            18,
            19,
            18,
            17,
            16,
            17,
            18,
            19,
            18,
            17,
        ]

        for x_position, y_position in enumerate(
            first_trace_rows
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

        for x_position, y_position in enumerate(
            second_trace_rows
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
            result.lead_segmentation.width,
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
            result.lead_segmentation.region_count,
            0,
        )

        self.assertGreater(
            len(
                result.lead_signals
            ),
            0,
        )

        self.assertGreater(
            result.reconstructed_signal.sample_count,
            0,
        )

    def test_pipeline_reconstructs_detected_lead_region_signal(self):
        ecg_file = self.create_image_file(
            self.create_trace_png_bytes()
        )

        result = run_ecg_image_pipeline(
            ecg_file
        )

        self.assertEqual(
            result.region_count,
            1,
        )

        self.assertEqual(
            len(
                result.lead_signals
            ),
            1,
        )

        lead_signal = result.lead_signals[0]

        self.assertEqual(
            lead_signal.index,
            1,
        )

        self.assertEqual(
            lead_signal.reconstructed_signal.sample_count,
            20,
        )

        self.assertEqual(
            lead_signal.reconstructed_signal.missing_count,
            0,
        )

        self.assertEqual(
            lead_signal.coverage_ratio,
            1.0,
        )

    @override_settings(
        ECG_LEAD_SEGMENTATION_MAX_GAP_ROWS=1,
        ECG_LEAD_SEGMENTATION_PADDING_ROWS=1,
    )
    def test_pipeline_reconstructs_multiple_detected_regions(self):
        ecg_file = self.create_image_file(
            self.create_two_region_trace_png_bytes(),
            filename="two-regions.png",
        )

        result = run_ecg_image_pipeline(
            ecg_file
        )

        self.assertEqual(
            result.region_count,
            2,
        )

        self.assertEqual(
            len(
                result.lead_signals
            ),
            2,
        )

        first = result.lead_signals[0]
        second = result.lead_signals[1]

        self.assertEqual(
            first.index,
            1,
        )

        self.assertEqual(
            second.index,
            2,
        )

        self.assertEqual(
            first.reconstructed_signal.sample_count,
            20,
        )

        self.assertEqual(
            second.reconstructed_signal.sample_count,
            20,
        )

        self.assertEqual(
            first.reconstructed_signal.missing_count,
            0,
        )

        self.assertEqual(
            second.reconstructed_signal.missing_count,
            0,
        )

        self.assertLess(
            first.region.bottom,
            second.region.top,
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

    def test_pipeline_skips_perspective_when_corners_are_not_supplied(
        self,
    ):
        ecg_file = self.create_image_file(
            self.create_trace_png_bytes()
        )

        result = run_ecg_image_pipeline(
            ecg_file
        )

        self.assertFalse(
            result.perspective_corrected
        )

        self.assertIsNone(
            result.perspective_correction
        )

        self.assertEqual(
            result.width,
            20,
        )

        self.assertEqual(
            result.height,
            12,
        )

    def test_pipeline_applies_perspective_when_corners_are_supplied(
        self,
    ):
        ecg_file = self.create_image_file(
            self.create_trace_png_bytes()
        )

        corners = ECGImageQuadrilateral(
            top_left=(
                0,
                0,
            ),
            top_right=(
                19,
                0,
            ),
            bottom_right=(
                19,
                11,
            ),
            bottom_left=(
                0,
                11,
            ),
        )

        result = run_ecg_image_pipeline(
            ecg_file,
            perspective_corners=corners,
        )

        self.assertTrue(
            result.perspective_corrected
        )

        self.assertIsNotNone(
            result.perspective_correction
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