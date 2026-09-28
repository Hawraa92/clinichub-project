import io
import tempfile
from dataclasses import replace
from unittest.mock import call, patch
from PIL import Image
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from appointments.tests.factories import AppointmentFactory
from ecg.models import ECGFile, ECGRecord
from ecg.services.calibration import (
    CalibratedECGSignal,
    ECGCalibrationError,
    ECGCalibrationParameters,
)
from ecg.services.grid_detection import (
    ECGGridDetectionError,
    ECGGridDetectionResult,
)
from ecg.services.image_pipeline import (
    ECGImagePipelineError,
    run_ecg_image_pipeline,
)
from ecg.services.lead_identification import (
    ECGLeadIdentificationError,
    identify_ecg_leads,
)
from ecg.services.lead_signal_extraction import (
    ECGLeadSignalExtractionError,
    extract_ecg_lead_signals,
)
from ecg.services.lead_segmentation import (
    ECGLeadLayoutCell,
    ECGLeadLayoutResult,
    ECGLeadRegion,
    ECGLeadSegmentationError,
)
from ecg.services.paper_detection import (
    ECGPaperDetectionError,
    ECGPaperDetectionResult,
)
from ecg.services.perspective import ECGImageQuadrilateral
from ecg.services.quality_assessment import (
    ECGQualityAssessmentError,
    ECGQualityAssessmentResult,
)

class ECGImagePipelineTests(TestCase):

    def setUp(self):
        self.private_media = tempfile.TemporaryDirectory()
        self.settings_override = override_settings(
            PRIVATE_MEDIA_ROOT=self.private_media.name
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

    # =========================================================
    # Test Image Helpers

    # =========================================================

    def create_trace_png_bytes(self):
        width = 20
        height = 12
        image = Image.new(
            "RGB",
            (width, height),
            color=(255, 255, 255),
        )
        trace_rows = [
            6, 5, 4, 5, 6,
            7, 6, 5, 4, 5,
            6, 7, 6, 5, 4,
            5, 6, 7, 6, 5,
        ]
        for x_position, y_position in enumerate(trace_rows):
            image.putpixel(
                (x_position, y_position),
                (0, 0, 0),
            )
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        return buffer.getvalue()

    def create_two_region_trace_png_bytes(self):
        width = 20
        height = 24
        image = Image.new(
            "RGB",
            (width, height),
            color=(255, 255, 255),
        )
        first_trace_rows = [
            5, 4, 3, 4, 5,
            6, 5, 4, 3, 4,
            5, 6, 5, 4, 3,
            4, 5, 6, 5, 4,
        ]
        second_trace_rows = [
            18, 17, 16, 17, 18,
            19, 18, 17, 16, 17,
            18, 19, 18, 17, 16,
            17, 18, 19, 18, 17,
        ]
        for x_position, y_position in enumerate(first_trace_rows):
            image.putpixel(
                (x_position, y_position),
                (0, 0, 0),
            )
        for x_position, y_position in enumerate(second_trace_rows):
            image.putpixel(
                (x_position, y_position),
                (0, 0, 0),
            )
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        return buffer.getvalue()

    def create_blank_png_bytes(self):
        image = Image.new(
            "RGB",
            (20, 12),
            color=(255, 255, 255),
        )
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
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

    # =========================================================
    # Calibration and Layout Helpers

    # =========================================================

    def create_grid_detection_result(self):
        return ECGGridDetectionResult(
            pixels_per_mm=5.0,
            x_spacing_pixels=5.0,
            y_spacing_pixels=5.0,
            x_grid_line_positions=(
                0.0,
                5.0,
                10.0,
                15.0,
            ),
            y_grid_line_positions=(
                0.0,
                5.0,
                10.0,
                15.0,
            ),
            axis_difference_ratio=0.0,
        )

    def create_calibrated_signal(self):
        parameters = ECGCalibrationParameters(
            pixels_per_mm=5.0,
            paper_speed_mm_per_s=25.0,
            gain_mm_per_mv=10.0,
        )
        return CalibratedECGSignal(
            time_seconds=(
                0.0,
                0.008,
            ),
            amplitude_mv=(
                0.0,
                0.02,
            ),
            parameters=parameters,
        )

    def create_lead_layout_result(self):
        rows = (
            ECGLeadRegion(
                index=1,
                top=0,
                bottom=4,
                active_top=1,
                active_bottom=3,
                candidate_pixel_count=20,
            ),
            ECGLeadRegion(
                index=2,
                top=4,
                bottom=8,
                active_top=5,
                active_bottom=7,
                candidate_pixel_count=20,
            ),
            ECGLeadRegion(
                index=3,
                top=8,
                bottom=12,
                active_top=9,
                active_bottom=11,
                candidate_pixel_count=20,
            ),
        )
        cells = []
        cell_index = 1
        for row in rows:
            for column_index in range(1, 5):
                left = (column_index - 1) * 5
                right = column_index * 5
                cells.append(
                    ECGLeadLayoutCell(
                        index=cell_index,
                        row_index=row.index,
                        column_index=column_index,
                        left=left,
                        right=right,
                        top=row.top,
                        bottom=row.bottom,
                        active_left=left,
                        active_right=right,
                        active_top=row.active_top,
                        active_bottom=row.active_bottom,
                        candidate_pixel_count=5,
                    )
                )
                cell_index += 1
        return ECGLeadLayoutResult(
            width=20,
            height=12,
            rows=rows,
            cells=tuple(cells),
        )


    # =========================================================
    # Synthetic 12-Cell Image / Layout Fixtures
    # =========================================================

    def create_twelve_cell_trace_png_bytes(self):
        """Build a synthetic 80x36 image: three rows and four 20x12 cells."""
        image = Image.new(
            "RGB", (80, 36), color=(255, 255, 255),
        )
        wave_offsets = (0, -1, -2, -1, 0, 1)

        for row_index in range(1, 4):
            for column_index in range(1, 5):
                left = (column_index - 1) * 20
                top = (row_index - 1) * 12
                baseline = 3 + ((row_index + column_index) % 3)

                for local_x in range(20):
                    local_y = baseline + wave_offsets[
                        local_x % len(wave_offsets)
                    ]
                    image.putpixel(
                        (left + local_x, top + local_y),
                        (0, 0, 0),
                    )

        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        return buffer.getvalue()

    def create_twelve_cell_layout_result(self):
        """Provide the known geometry for the synthetic 80x36 image."""
        rows = tuple(
            ECGLeadRegion(
                index=row_index,
                top=(row_index - 1) * 12,
                bottom=row_index * 12,
                active_top=(row_index - 1) * 12 + 1,
                active_bottom=row_index * 12 - 1,
                candidate_pixel_count=80,
            )
            for row_index in range(1, 4)
        )
        cells = []
        index = 1
        for row in rows:
            for column_index in range(1, 5):
                left = (column_index - 1) * 20
                right = column_index * 20
                cells.append(
                    ECGLeadLayoutCell(
                        index=index,
                        row_index=row.index,
                        column_index=column_index,
                        left=left,
                        right=right,
                        top=row.top,
                        bottom=row.bottom,
                        active_left=left + 1,
                        active_right=right - 1,
                        active_top=row.active_top,
                        active_bottom=row.active_bottom,
                        candidate_pixel_count=20,
                    )
                )
                index += 1
        return ECGLeadLayoutResult(
            width=80,
            height=36,
            rows=rows,
            cells=tuple(cells),
        )

    # =========================================================
    # Original Image Pipeline Tests

    # =========================================================

    def test_pipeline_reconstructs_signal_from_ecg_image(self):
        ecg_file = self.create_image_file(
            self.create_trace_png_bytes()
        )
        result = run_ecg_image_pipeline(ecg_file)
        self.assertEqual(result.width, 20)
        self.assertEqual(result.height, 12)
        self.assertEqual(
            result.reconstructed_signal.sample_count,
            20,
        )
        self.assertEqual(
            result.reconstructed_signal.missing_count,
            0,
        )
        self.assertEqual(result.coverage_ratio, 1.0)
        self.assertEqual(len(result.signal_values), 20)
        self.assertEqual(
            result.x_positions,
            tuple(range(20)),
        )

    def test_pipeline_exposes_each_processing_stage(self):
        ecg_file = self.create_image_file(
            self.create_trace_png_bytes()
        )
        result = run_ecg_image_pipeline(ecg_file)
        self.assertEqual(result.processed_image.width, 20)
        self.assertEqual(result.trace_candidates.width, 20)
        self.assertEqual(result.lead_segmentation.width, 20)
        self.assertEqual(result.reconstructed_signal.width, 20)
        self.assertGreater(
            result.trace_candidates.candidate_pixel_count,
            0,
        )
        self.assertGreater(
            result.lead_segmentation.region_count,
            0,
        )
        self.assertGreater(len(result.lead_signals), 0)
        self.assertGreater(
            result.reconstructed_signal.sample_count,
            0,
        )

    def test_pipeline_reconstructs_detected_lead_region_signal(self):
        ecg_file = self.create_image_file(
            self.create_trace_png_bytes()
        )
        result = run_ecg_image_pipeline(ecg_file)
        self.assertEqual(result.region_count, 1)
        self.assertEqual(len(result.lead_signals), 1)
        lead_signal = result.lead_signals[0]
        self.assertEqual(lead_signal.index, 1)
        self.assertEqual(
            lead_signal.reconstructed_signal.sample_count,
            20,
        )
        self.assertEqual(
            lead_signal.reconstructed_signal.missing_count,
            0,
        )
        self.assertEqual(lead_signal.coverage_ratio, 1.0)

    @override_settings(
        ECG_LEAD_SEGMENTATION_MAX_GAP_ROWS=1,
        ECG_LEAD_SEGMENTATION_PADDING_ROWS=1,
    )

    def test_pipeline_reconstructs_multiple_detected_regions(self):
        ecg_file = self.create_image_file(
            self.create_two_region_trace_png_bytes(),
            filename="two-regions.png",
        )
        result = run_ecg_image_pipeline(ecg_file)
        self.assertEqual(result.region_count, 2)
        self.assertEqual(len(result.lead_signals), 2)
        first = result.lead_signals[0]
        second = result.lead_signals[1]
        self.assertEqual(first.index, 1)
        self.assertEqual(second.index, 2)
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
        with self.assertRaises(ECGImagePipelineError):
            run_ecg_image_pipeline(ecg_file)

    def test_blank_image_is_wrapped_as_pipeline_error(self):
        ecg_file = self.create_image_file(
            self.create_blank_png_bytes()
        )
        with self.assertRaises(ECGImagePipelineError):
            run_ecg_image_pipeline(ecg_file)

    def test_pipeline_rejects_region_without_trace(self):
        ecg_file = self.create_image_file(
            self.create_trace_png_bytes()
        )
        with self.assertRaises(ECGImagePipelineError):
            run_ecg_image_pipeline(
                ecg_file,
                region_top=0,
                region_bottom=3,
            )

    # =========================================================
    # Perspective Correction Tests

    # =========================================================

    def test_pipeline_skips_perspective_when_corners_are_not_supplied(
        self,
    ):
        ecg_file = self.create_image_file(
            self.create_trace_png_bytes()
        )
        result = run_ecg_image_pipeline(ecg_file)
        self.assertFalse(result.perspective_corrected)
        self.assertIsNone(result.perspective_correction)
        self.assertFalse(result.paper_detected)
        self.assertIsNone(result.paper_detection)
        self.assertEqual(result.width, 20)
        self.assertEqual(result.height, 12)

    def test_pipeline_applies_perspective_when_corners_are_supplied(
        self,
    ):
        ecg_file = self.create_image_file(
            self.create_trace_png_bytes()
        )
        corners = ECGImageQuadrilateral(
            top_left=(0, 0),
            top_right=(19, 0),
            bottom_right=(19, 11),
            bottom_left=(0, 11),
        )
        result = run_ecg_image_pipeline(
            ecg_file,
            perspective_corners=corners,
        )
        self.assertTrue(result.perspective_corrected)
        self.assertIsNotNone(result.perspective_correction)
        self.assertFalse(result.paper_detected)
        self.assertIsNone(result.paper_detection)
        self.assertEqual(result.width, 20)
        self.assertEqual(result.height, 12)
        self.assertEqual(
            result.reconstructed_signal.sample_count,
            20,
        )

    def test_pipeline_auto_detects_paper_and_applies_perspective(
        self,
    ):
        ecg_file = self.create_image_file(
            self.create_trace_png_bytes()
        )
        corners = ECGImageQuadrilateral(
            top_left=(0, 0),
            top_right=(19, 0),
            bottom_right=(19, 11),
            bottom_left=(0, 11),
        )
        detection_result = ECGPaperDetectionResult(
            corners=corners,
            contour_area=209.0,
            image_area=240,
            area_ratio=209.0 / 240.0,
            candidate_count=1,
        )
        with patch(
            "ecg.services.image_pipeline.detect_ecg_paper_corners",
            return_value=detection_result,
        ) as detect_mock:
            result = run_ecg_image_pipeline(
                ecg_file,
                auto_detect_paper=True,
            )
        detect_mock.assert_called_once()
        self.assertTrue(result.paper_detected)
        self.assertIs(
            result.paper_detection,
            detection_result,
        )
        self.assertTrue(result.perspective_corrected)
        self.assertIsNotNone(result.perspective_correction)
        self.assertEqual(result.width, 20)
        self.assertEqual(result.height, 12)
        self.assertEqual(
            result.reconstructed_signal.sample_count,
            20,
        )

    def test_pipeline_wraps_automatic_paper_detection_failure(
        self,
    ):
        ecg_file = self.create_image_file(
            self.create_trace_png_bytes()
        )
        with patch(
            "ecg.services.image_pipeline.detect_ecg_paper_corners",
            side_effect=ECGPaperDetectionError(
                "No reliable paper boundary."
            ),
        ):
            with self.assertRaises(ECGImagePipelineError):
                run_ecg_image_pipeline(
                    ecg_file,
                    auto_detect_paper=True,
                )

    def test_manual_corners_take_priority_over_automatic_detection(
        self,
    ):
        ecg_file = self.create_image_file(
            self.create_trace_png_bytes()
        )
        corners = ECGImageQuadrilateral(
            top_left=(0, 0),
            top_right=(19, 0),
            bottom_right=(19, 11),
            bottom_left=(0, 11),
        )
        with patch(
            "ecg.services.image_pipeline.detect_ecg_paper_corners"
        ) as detect_mock:
            result = run_ecg_image_pipeline(
                ecg_file,
                perspective_corners=corners,
                auto_detect_paper=True,
            )
        detect_mock.assert_not_called()
        self.assertTrue(result.perspective_corrected)
        self.assertFalse(result.paper_detected)
        self.assertIsNone(result.paper_detection)
        self.assertEqual(result.width, 20)
        self.assertEqual(result.height, 12)

    # =========================================================
    # 2D Lead Layout Tests

    # =========================================================

    def test_pipeline_skips_2d_layout_detection_by_default(
        self,
    ):
        ecg_file = self.create_image_file(
            self.create_trace_png_bytes()
        )
        with patch(
            "ecg.services.image_pipeline.segment_ecg_lead_layout"
        ) as layout_mock:
            result = run_ecg_image_pipeline(ecg_file)
        layout_mock.assert_not_called()
        self.assertIsNone(result.lead_layout)
        self.assertFalse(result.layout_detected)
        self.assertEqual(result.layout_row_count, 0)
        self.assertEqual(result.layout_cell_count, 0)
        self.assertEqual(
            result.layout_columns_per_row,
            (),
        )

    def test_pipeline_detects_2d_layout_when_enabled(
        self,
    ):
        ecg_file = self.create_image_file(
            self.create_trace_png_bytes()
        )
        lead_layout = self.create_lead_layout_result()
        with patch(
            "ecg.services.image_pipeline.segment_ecg_lead_layout",
            return_value=lead_layout,
        ) as layout_mock:
            result = run_ecg_image_pipeline(
                ecg_file,
                auto_detect_layout=True,
            )
        layout_mock.assert_called_once_with(
            result.trace_candidates
        )
        self.assertIs(result.lead_layout, lead_layout)
        self.assertTrue(result.layout_detected)
        self.assertEqual(result.layout_row_count, 3)
        self.assertEqual(result.layout_cell_count, 12)
        self.assertEqual(
            result.layout_columns_per_row,
            (4, 4, 4),
        )

    def test_pipeline_wraps_2d_layout_failure_safely(
        self,
    ):
        ecg_file = self.create_image_file(
            self.create_trace_png_bytes()
        )
        with patch(
            "ecg.services.image_pipeline.segment_ecg_lead_layout",
            side_effect=ECGLeadSegmentationError(
                "Layout segmentation failed."
            ),
        ):
            with self.assertRaises(
                ECGImagePipelineError
            ) as context:
                run_ecg_image_pipeline(
                    ecg_file,
                    auto_detect_layout=True,
                )
        self.assertEqual(
            str(context.exception),
            (
                "The ECG 2D lead layout could not be "
                "segmented safely from the image."
            ),
        )

    # =========================================================
    # Grid Detection and Calibration Tests

    # =========================================================

    def test_pipeline_skips_grid_detection_and_calibration_by_default(
        self,
    ):
        ecg_file = self.create_image_file(
            self.create_trace_png_bytes()
        )
        with (
            patch(
                "ecg.services.image_pipeline.detect_ecg_grid_scale"
            ) as grid_mock,
            patch(
                "ecg.services.image_pipeline.calibrate_reconstructed_signal"
            ) as calibration_mock,
        ):
            result = run_ecg_image_pipeline(ecg_file)
        grid_mock.assert_not_called()
        calibration_mock.assert_not_called()
        self.assertIsNone(result.grid_detection)
        self.assertIsNone(result.calibrated_signal)
        self.assertFalse(result.calibrated)
        for lead_signal in result.lead_signals:
            self.assertIsNone(lead_signal.calibrated_signal)
            self.assertFalse(lead_signal.calibrated)

    def test_pipeline_automatically_detects_grid_and_calibrates_signal(
        self,
    ):
        ecg_file = self.create_image_file(
            self.create_trace_png_bytes()
        )
        grid_detection = self.create_grid_detection_result()
        overall_calibrated_signal = self.create_calibrated_signal()
        lead_calibrated_signal = self.create_calibrated_signal()
        with (
            patch(
                "ecg.services.image_pipeline.detect_ecg_grid_scale",
                return_value=grid_detection,
            ) as grid_mock,
            patch(
                "ecg.services.image_pipeline.calibrate_reconstructed_signal",
                side_effect=(
                    overall_calibrated_signal,
                    lead_calibrated_signal,
                ),
            ) as calibration_mock,
        ):
            result = run_ecg_image_pipeline(
                ecg_file,
                auto_calibrate=True,
            )
        grid_mock.assert_called_once_with(
            result.processed_image
        )
        self.assertEqual(calibration_mock.call_count, 2)
        self.assertEqual(
            calibration_mock.call_args_list,
            [
                call(
                    result.reconstructed_signal,
                    pixels_per_mm=grid_detection.pixels_per_mm,
                ),
                call(
                    result.lead_signals[0].reconstructed_signal,
                    pixels_per_mm=grid_detection.pixels_per_mm,
                ),
            ],
        )
        self.assertIs(result.grid_detection, grid_detection)
        self.assertIs(
            result.calibrated_signal,
            overall_calibrated_signal,
        )
        self.assertTrue(result.calibrated)
        self.assertEqual(result.pixels_per_mm, 5.0)
        self.assertEqual(len(result.lead_signals), 1)
        self.assertTrue(result.lead_signals[0].calibrated)
        self.assertIs(
            result.lead_signals[0].calibrated_signal,
            lead_calibrated_signal,
        )

    @override_settings(
        ECG_LEAD_SEGMENTATION_MAX_GAP_ROWS=1,
        ECG_LEAD_SEGMENTATION_PADDING_ROWS=1,
    )

    def test_pipeline_calibrates_each_detected_lead_with_same_grid_scale(
        self,
    ):
        ecg_file = self.create_image_file(
            self.create_two_region_trace_png_bytes(),
            filename="two-regions-calibrated.png",
        )
        grid_detection = self.create_grid_detection_result()
        overall_calibrated_signal = self.create_calibrated_signal()
        first_lead_calibrated_signal = self.create_calibrated_signal()
        second_lead_calibrated_signal = self.create_calibrated_signal()
        with (
            patch(
                "ecg.services.image_pipeline.detect_ecg_grid_scale",
                return_value=grid_detection,
            ) as grid_mock,
            patch(
                "ecg.services.image_pipeline.calibrate_reconstructed_signal",
                side_effect=(
                    overall_calibrated_signal,
                    first_lead_calibrated_signal,
                    second_lead_calibrated_signal,
                ),
            ) as calibration_mock,
        ):
            result = run_ecg_image_pipeline(
                ecg_file,
                auto_calibrate=True,
            )
        grid_mock.assert_called_once_with(
            result.processed_image
        )
        self.assertEqual(result.region_count, 2)
        self.assertEqual(calibration_mock.call_count, 3)
        self.assertEqual(
            calibration_mock.call_args_list,
            [
                call(
                    result.reconstructed_signal,
                    pixels_per_mm=grid_detection.pixels_per_mm,
                ),
                call(
                    result.lead_signals[0].reconstructed_signal,
                    pixels_per_mm=grid_detection.pixels_per_mm,
                ),
                call(
                    result.lead_signals[1].reconstructed_signal,
                    pixels_per_mm=grid_detection.pixels_per_mm,
                ),
            ],
        )
        self.assertIs(
            result.calibrated_signal,
            overall_calibrated_signal,
        )
        self.assertIs(
            result.lead_signals[0].calibrated_signal,
            first_lead_calibrated_signal,
        )
        self.assertIs(
            result.lead_signals[1].calibrated_signal,
            second_lead_calibrated_signal,
        )
        self.assertTrue(result.lead_signals[0].calibrated)
        self.assertTrue(result.lead_signals[1].calibrated)

    def test_pipeline_wraps_grid_detection_failure_during_auto_calibration(
        self,
    ):
        ecg_file = self.create_image_file(
            self.create_trace_png_bytes()
        )
        with patch(
            "ecg.services.image_pipeline.detect_ecg_grid_scale",
            side_effect=ECGGridDetectionError(
                "No reliable ECG grid scale."
            ),
        ):
            with self.assertRaises(
                ECGImagePipelineError
            ) as context:
                run_ecg_image_pipeline(
                    ecg_file,
                    auto_calibrate=True,
                )
        self.assertEqual(
            str(context.exception),
            "The ECG grid scale could not be detected safely.",
        )

    def test_pipeline_wraps_calibration_failure_after_grid_detection(
        self,
    ):
        ecg_file = self.create_image_file(
            self.create_trace_png_bytes()
        )
        grid_detection = self.create_grid_detection_result()
        with (
            patch(
                "ecg.services.image_pipeline.detect_ecg_grid_scale",
                return_value=grid_detection,
            ),
            patch(
                "ecg.services.image_pipeline.calibrate_reconstructed_signal",
                side_effect=ECGCalibrationError(
                    "Calibration failed."
                ),
            ),
        ):
            with self.assertRaises(
                ECGImagePipelineError
            ) as context:
                run_ecg_image_pipeline(
                    ecg_file,
                    auto_calibrate=True,
                )
        self.assertEqual(
            str(context.exception),
            (
                "The reconstructed ECG signal could not "
                "be calibrated safely."
            ),
        )

    def test_pipeline_wraps_lead_calibration_failure_safely(
        self,
    ):
        ecg_file = self.create_image_file(
            self.create_trace_png_bytes()
        )
        grid_detection = self.create_grid_detection_result()
        overall_calibrated_signal = self.create_calibrated_signal()
        with (
            patch(
                "ecg.services.image_pipeline.detect_ecg_grid_scale",
                return_value=grid_detection,
            ),
            patch(
                "ecg.services.image_pipeline.calibrate_reconstructed_signal",
                side_effect=(
                    overall_calibrated_signal,
                    ECGCalibrationError(
                        "Lead calibration failed."
                    ),
                ),
            ),
        ):
            with self.assertRaises(
                ECGImagePipelineError
            ) as context:
                run_ecg_image_pipeline(
                    ecg_file,
                    auto_calibrate=True,
                )
        self.assertEqual(
            str(context.exception),
            (
                "The reconstructed ECG signal for detected "
                "region 1 could not be calibrated safely."
            ),
        )

    # =========================================================
    # Quality Assessment Integration Tests

    # =========================================================

    def test_pipeline_skips_quality_assessment_by_default(self):
        ecg_file = self.create_image_file(
            self.create_trace_png_bytes()
        )
        with patch(
            "ecg.services.image_pipeline.assess_ecg_processing_quality"
        ) as quality_mock:
            result = run_ecg_image_pipeline(ecg_file)
        quality_mock.assert_not_called()
        self.assertIsNone(result.quality_assessment)
        self.assertFalse(result.quality_assessed)
        self.assertIsNone(result.processing_usable)
        self.assertIsNone(result.processing_quality_level)

    def test_pipeline_assesses_reconstructed_signal_when_enabled(self):
        ecg_file = self.create_image_file(
            self.create_trace_png_bytes()
        )
        result = run_ecg_image_pipeline(
            ecg_file,
            auto_assess_quality=True,
        )
        self.assertTrue(result.quality_assessed)
        self.assertTrue(result.processing_usable)
        self.assertEqual(
            result.processing_quality_level,
            "high",
        )
        self.assertEqual(
            result.quality_assessment.sample_count,
            20,
        )
        self.assertEqual(
            result.quality_assessment.missing_count,
            0,
        )
        self.assertEqual(
            result.quality_assessment.coverage_ratio,
            1.0,
        )
        self.assertEqual(
            result.quality_assessment.reasons,
            (),
        )

    def test_pipeline_quality_does_not_enable_layout_or_grid_implicitly(
        self,
    ):
        ecg_file = self.create_image_file(
            self.create_trace_png_bytes()
        )
        with (
            patch(
                "ecg.services.image_pipeline.segment_ecg_lead_layout"
            ) as layout_mock,
            patch(
                "ecg.services.image_pipeline.detect_ecg_grid_scale"
            ) as grid_mock,
        ):
            result = run_ecg_image_pipeline(
                ecg_file,
                auto_assess_quality=True,
            )
        layout_mock.assert_not_called()
        grid_mock.assert_not_called()
        self.assertTrue(result.processing_usable)
        self.assertFalse(
            result.quality_assessment.layout_detected
        )
        self.assertFalse(
            result.quality_assessment.grid_detected
        )
        self.assertFalse(
            result.quality_assessment.calibrated
        )

    def test_pipeline_quality_includes_optional_detected_layout(self):
        ecg_file = self.create_image_file(
            self.create_trace_png_bytes()
        )
        lead_layout = self.create_lead_layout_result()
        with patch(
            "ecg.services.image_pipeline.segment_ecg_lead_layout",
            return_value=lead_layout,
        ) as layout_mock:
            result = run_ecg_image_pipeline(
                ecg_file,
                auto_detect_layout=True,
                auto_assess_quality=True,
            )
        layout_mock.assert_called_once_with(
            result.trace_candidates
        )
        self.assertIs(result.lead_layout, lead_layout)
        self.assertTrue(
            result.quality_assessment.layout_detected
        )
        self.assertEqual(
            result.quality_assessment.layout_row_count,
            3,
        )
        self.assertEqual(
            result.quality_assessment.layout_cell_count,
            12,
        )
        self.assertTrue(result.processing_usable)

    def test_pipeline_quality_includes_calibration_after_it_completes(
        self,
    ):
        ecg_file = self.create_image_file(
            self.create_trace_png_bytes()
        )
        grid_detection = self.create_grid_detection_result()
        overall_calibrated = self.create_calibrated_signal()
        lead_calibrated = self.create_calibrated_signal()
        with (
            patch(
                "ecg.services.image_pipeline.detect_ecg_grid_scale",
                return_value=grid_detection,
            ) as grid_mock,
            patch(
                "ecg.services.image_pipeline.calibrate_reconstructed_signal",
                side_effect=(
                    overall_calibrated,
                    lead_calibrated,
                ),
            ) as calibration_mock,
        ):
            result = run_ecg_image_pipeline(
                ecg_file,
                auto_calibrate=True,
                auto_assess_quality=True,
            )
        grid_mock.assert_called_once_with(
            result.processed_image
        )
        self.assertEqual(calibration_mock.call_count, 2)
        self.assertIs(
            result.calibrated_signal,
            overall_calibrated,
        )
        self.assertTrue(
            result.quality_assessment.grid_detected
        )
        self.assertTrue(
            result.quality_assessment.calibrated
        )
        self.assertTrue(result.processing_usable)

    def test_pipeline_passes_required_options_to_quality_assessment(
        self,
    ):
        ecg_file = self.create_image_file(
            self.create_trace_png_bytes()
        )
        lead_layout = self.create_lead_layout_result()
        grid_detection = self.create_grid_detection_result()
        overall_calibrated = self.create_calibrated_signal()
        lead_calibrated = self.create_calibrated_signal()
        quality_result = ECGQualityAssessmentResult(
            usable=True,
            quality_level="high",
            coverage_ratio=1.0,
            sample_count=20,
            missing_count=0,
            layout_detected=True,
            layout_row_count=3,
            layout_cell_count=12,
            grid_detected=True,
            calibrated=True,
            reasons=(),
            warnings=(),
        )
        with (
            patch(
                "ecg.services.image_pipeline.segment_ecg_lead_layout",
                return_value=lead_layout,
            ),
            patch(
                "ecg.services.image_pipeline.detect_ecg_grid_scale",
                return_value=grid_detection,
            ),
            patch(
                "ecg.services.image_pipeline.calibrate_reconstructed_signal",
                side_effect=(
                    overall_calibrated,
                    lead_calibrated,
                ),
            ),
            patch(
                "ecg.services.image_pipeline.assess_ecg_processing_quality",
                return_value=quality_result,
            ) as quality_mock,
        ):
            result = run_ecg_image_pipeline(
                ecg_file,
                auto_detect_layout=True,
                auto_calibrate=True,
                auto_assess_quality=True,
            )
        quality_mock.assert_called_once_with(
            result.reconstructed_signal,
            lead_layout=lead_layout,
            grid_detection=grid_detection,
            calibrated_signal=overall_calibrated,
            require_layout=True,
            require_grid=True,
            require_calibration=True,
        )
        self.assertIs(result.quality_assessment, quality_result)
        self.assertTrue(result.quality_assessed)

    def test_pipeline_exposes_insufficient_quality_without_misreporting_success(
        self,
    ):
        ecg_file = self.create_image_file(
            self.create_trace_png_bytes()
        )
        quality_result = ECGQualityAssessmentResult(
            usable=False,
            quality_level="insufficient",
            coverage_ratio=0.8,
            sample_count=20,
            missing_count=4,
            layout_detected=False,
            layout_row_count=0,
            layout_cell_count=0,
            grid_detected=False,
            calibrated=False,
            reasons=(
                "Coverage is below the configured threshold.",
            ),
            warnings=(
                "Some reconstructed samples are missing.",
            ),
        )
        with patch(
            "ecg.services.image_pipeline.assess_ecg_processing_quality",
            return_value=quality_result,
        ) as quality_mock:
            result = run_ecg_image_pipeline(
                ecg_file,
                auto_assess_quality=True,
            )
        quality_mock.assert_called_once()
        self.assertIs(
            result.quality_assessment,
            quality_result,
        )
        self.assertTrue(result.quality_assessed)
        self.assertFalse(result.processing_usable)
        self.assertEqual(
            result.processing_quality_level,
            "insufficient",
        )
        self.assertTrue(
            result.quality_assessment.reasons
        )

    def test_pipeline_wraps_quality_assessment_failure_safely(
        self,
    ):
        ecg_file = self.create_image_file(
            self.create_trace_png_bytes()
        )
        with patch(
            "ecg.services.image_pipeline.assess_ecg_processing_quality",
            side_effect=ECGQualityAssessmentError(
                "Invalid quality metrics."
            ),
        ):
            with self.assertRaises(
                ECGImagePipelineError
            ) as context:
                run_ecg_image_pipeline(
                    ecg_file,
                    auto_assess_quality=True,
                )
        self.assertEqual(
            str(context.exception),
            (
                "The ECG processing quality could not "
                "be assessed safely."
            ),
        )
        self.assertIsInstance(
            context.exception.__cause__,
            ECGQualityAssessmentError,
        )

    # =========================================================
    # NEW: ECG Lead Identification Integration Tests

    # =========================================================

    def test_pipeline_skips_lead_identification_by_default(self):
        ecg_file = self.create_image_file(
            self.create_trace_png_bytes()
        )
        with patch(
            "ecg.services.image_pipeline.identify_ecg_leads"
        ) as identify_mock:
            result = run_ecg_image_pipeline(ecg_file)
        identify_mock.assert_not_called()
        self.assertIsNone(result.lead_identification)
        self.assertFalse(result.leads_identified)
        self.assertEqual(result.identified_lead_count, 0)
        self.assertEqual(result.identified_lead_names, ())

    def test_detecting_layout_alone_does_not_assign_lead_names(self):
        ecg_file = self.create_image_file(
            self.create_trace_png_bytes()
        )
        layout = self.create_lead_layout_result()
        with (
            patch(
                "ecg.services.image_pipeline.segment_ecg_lead_layout",
                return_value=layout,
            ) as layout_mock,
            patch(
                "ecg.services.image_pipeline.identify_ecg_leads"
            ) as identify_mock,
        ):
            result = run_ecg_image_pipeline(
                ecg_file,
                auto_detect_layout=True,
            )
        layout_mock.assert_called_once_with(
            result.trace_candidates
        )
        identify_mock.assert_not_called()
        self.assertIs(result.lead_layout, layout)
        self.assertTrue(result.layout_detected)
        self.assertFalse(result.leads_identified)
        self.assertEqual(result.identified_lead_names, ())

    def test_explicit_lead_format_requires_layout_detection(self):
        ecg_file = self.create_image_file(
            self.create_trace_png_bytes()
        )
        with patch(
            "ecg.services.image_pipeline.process_ecg_image"
        ) as processing_mock:
            with self.assertRaises(
                ECGImagePipelineError
            ) as context:
                run_ecg_image_pipeline(
                    ecg_file,
                    lead_layout_format="standard_3x4",
                )
        processing_mock.assert_not_called()
        self.assertEqual(
            str(context.exception),
            "ECG lead identification requires auto_detect_layout=True.",
        )

    def test_pipeline_identifies_twelve_cells_with_explicit_3x4_format(
        self,
    ):
        ecg_file = self.create_image_file(
            self.create_trace_png_bytes()
        )
        layout = self.create_lead_layout_result()
        with patch(
            "ecg.services.image_pipeline.segment_ecg_lead_layout",
            return_value=layout,
        ) as layout_mock:
            result = run_ecg_image_pipeline(
                ecg_file,
                auto_detect_layout=True,
                lead_layout_format="standard_3x4",
            )
        layout_mock.assert_called_once_with(
            result.trace_candidates
        )
        self.assertIs(result.lead_layout, layout)
        self.assertTrue(result.leads_identified)
        self.assertEqual(result.identified_lead_count, 12)
        self.assertTrue(
            result.lead_identification.complete_12_lead
        )
        self.assertEqual(
            result.identified_lead_names,
            (
                "I", "aVR", "V1", "V4",
                "II", "aVL", "V2", "V5",
                "III", "aVF", "V3", "V6",
            ),
        )
        self.assertIs(
            result.lead_identification.get_lead("I").cell,
            layout.cells[0],
        )
        self.assertIs(
            result.lead_identification.get_lead("V6").cell,
            layout.cells[11],
        )
        # Cell naming does not create 12 independent digital signals.
        self.assertEqual(result.region_count, 1)
        self.assertEqual(len(result.lead_signals), 1)

    def test_pipeline_passes_exact_layout_and_format_to_identifier(
        self,
    ):
        ecg_file = self.create_image_file(
            self.create_trace_png_bytes()
        )
        layout = self.create_lead_layout_result()
        named_result = identify_ecg_leads(
            layout,
            layout_format="standard_3x4",
        )
        with (
            patch(
                "ecg.services.image_pipeline.segment_ecg_lead_layout",
                return_value=layout,
            ),
            patch(
                "ecg.services.image_pipeline.identify_ecg_leads",
                return_value=named_result,
            ) as identify_mock,
        ):
            result = run_ecg_image_pipeline(
                ecg_file,
                auto_detect_layout=True,
                lead_layout_format="standard_3x4",
            )
        identify_mock.assert_called_once_with(
            layout,
            layout_format="standard_3x4",
        )
        self.assertIs(
            result.lead_identification,
            named_result,
        )

    def test_pipeline_wraps_unsupported_lead_format_safely(self):
        ecg_file = self.create_image_file(
            self.create_trace_png_bytes()
        )
        layout = self.create_lead_layout_result()
        with patch(
            "ecg.services.image_pipeline.segment_ecg_lead_layout",
            return_value=layout,
        ):
            with self.assertRaises(
                ECGImagePipelineError
            ) as context:
                run_ecg_image_pipeline(
                    ecg_file,
                    auto_detect_layout=True,
                    lead_layout_format="unknown_3x4",
                )
        self.assertEqual(
            str(context.exception),
            "The ECG lead names could not be assigned safely.",
        )
        self.assertIsInstance(
            context.exception.__cause__,
            ECGLeadIdentificationError,
        )

    def test_pipeline_wraps_incomplete_named_layout_safely(self):
        ecg_file = self.create_image_file(
            self.create_trace_png_bytes()
        )
        complete_layout = self.create_lead_layout_result()
        incomplete_layout = replace(
            complete_layout,
            cells=complete_layout.cells[:-1],
        )
        with patch(
            "ecg.services.image_pipeline.segment_ecg_lead_layout",
            return_value=incomplete_layout,
        ):
            with self.assertRaises(
                ECGImagePipelineError
            ) as context:
                run_ecg_image_pipeline(
                    ecg_file,
                    auto_detect_layout=True,
                    lead_layout_format="standard_3x4",
                )
        self.assertEqual(
            str(context.exception),
            "The ECG lead names could not be assigned safely.",
        )
        self.assertIsInstance(
            context.exception.__cause__,
            ECGLeadIdentificationError,
        )

    def test_layout_failure_prevents_lead_identification(self):
        ecg_file = self.create_image_file(
            self.create_trace_png_bytes()
        )
        with (
            patch(
                "ecg.services.image_pipeline.segment_ecg_lead_layout",
                side_effect=ECGLeadSegmentationError(
                    "Layout failure."
                ),
            ),
            patch(
                "ecg.services.image_pipeline.identify_ecg_leads"
            ) as identify_mock,
        ):
            with self.assertRaises(
                ECGImagePipelineError
            ) as context:
                run_ecg_image_pipeline(
                    ecg_file,
                    auto_detect_layout=True,
                    lead_layout_format="standard_3x4",
                )
        identify_mock.assert_not_called()
        self.assertEqual(
            str(context.exception),
            (
                "The ECG 2D lead layout could not be "
                "segmented safely from the image."
            ),
        )

    def test_lead_identification_coexists_with_quality_and_calibration(
        self,
    ):
        ecg_file = self.create_image_file(
            self.create_trace_png_bytes()
        )
        layout = self.create_lead_layout_result()
        grid_detection = self.create_grid_detection_result()
        overall_calibrated = self.create_calibrated_signal()
        region_calibrated = self.create_calibrated_signal()
        with (
            patch(
                "ecg.services.image_pipeline.segment_ecg_lead_layout",
                return_value=layout,
            ),
            patch(
                "ecg.services.image_pipeline.detect_ecg_grid_scale",
                return_value=grid_detection,
            ),
            patch(
                "ecg.services.image_pipeline.calibrate_reconstructed_signal",
                side_effect=(
                    overall_calibrated,
                    region_calibrated,
                ),
            ) as calibration_mock,
        ):
            result = run_ecg_image_pipeline(
                ecg_file,
                auto_detect_layout=True,
                lead_layout_format="standard_3x4",
                auto_calibrate=True,
                auto_assess_quality=True,
            )
        self.assertTrue(result.leads_identified)
        self.assertEqual(result.identified_lead_count, 12)
        self.assertIs(
            result.grid_detection,
            grid_detection,
        )
        self.assertIs(
            result.calibrated_signal,
            overall_calibrated,
        )
        self.assertEqual(
            calibration_mock.call_count,
            2,
        )
        self.assertTrue(result.quality_assessed)
        self.assertTrue(result.processing_usable)
        self.assertTrue(
            result.quality_assessment.layout_detected
        )
        self.assertTrue(
            result.quality_assessment.grid_detected
        )
        self.assertTrue(
            result.quality_assessment.calibrated
        )

    # =========================================================
    # NEW: Independent Per-Lead Extraction / Pipeline Integration
    # =========================================================

    def test_pipeline_skips_independent_lead_extraction_by_default(self):
        ecg_file = self.create_image_file(
            self.create_trace_png_bytes()
        )
        with patch(
            "ecg.services.image_pipeline.extract_ecg_lead_signals"
        ) as extract_mock:
            result = run_ecg_image_pipeline(ecg_file)

        extract_mock.assert_not_called()
        self.assertIsNone(result.lead_signal_extraction)
        self.assertFalse(result.per_lead_extracted)
        self.assertEqual(result.per_lead_signal_count, 0)
        self.assertEqual(result.per_lead_signal_names, ())
        self.assertEqual(result.per_lead_signals, ())

    def test_naming_cells_alone_does_not_extract_cell_signals(self):
        ecg_file = self.create_image_file(
            self.create_trace_png_bytes()
        )
        layout = self.create_lead_layout_result()
        with (
            patch(
                "ecg.services.image_pipeline.segment_ecg_lead_layout",
                return_value=layout,
            ),
            patch(
                "ecg.services.image_pipeline.extract_ecg_lead_signals"
            ) as extract_mock,
        ):
            result = run_ecg_image_pipeline(
                ecg_file,
                auto_detect_layout=True,
                lead_layout_format="standard_3x4",
            )

        extract_mock.assert_not_called()
        self.assertTrue(result.leads_identified)
        self.assertEqual(result.identified_lead_count, 12)
        self.assertFalse(result.per_lead_extracted)
        self.assertEqual(result.per_lead_signal_count, 0)

    def test_independent_extraction_rejects_missing_explicit_format_early(self):
        ecg_file = self.create_image_file(
            self.create_trace_png_bytes()
        )
        with patch(
            "ecg.services.image_pipeline.process_ecg_image"
        ) as image_mock:
            with self.assertRaises(ECGImagePipelineError) as context:
                run_ecg_image_pipeline(
                    ecg_file,
                    auto_detect_layout=True,
                    auto_extract_lead_signals=True,
                )

        image_mock.assert_not_called()
        self.assertEqual(
            str(context.exception),
            "Independent ECG lead signal extraction requires "
            "an explicit lead_layout_format.",
        )

    def test_independent_extraction_requires_layout_detection(self):
        ecg_file = self.create_image_file(
            self.create_trace_png_bytes()
        )
        with patch(
            "ecg.services.image_pipeline.process_ecg_image"
        ) as image_mock:
            with self.assertRaises(ECGImagePipelineError) as context:
                run_ecg_image_pipeline(
                    ecg_file,
                    lead_layout_format="standard_3x4",
                    auto_extract_lead_signals=True,
                )

        image_mock.assert_not_called()
        self.assertEqual(
            str(context.exception),
            "ECG lead identification requires auto_detect_layout=True.",
        )

    def test_pipeline_actually_extracts_twelve_named_cell_signals(self):
        ecg_file = self.create_image_file(
            self.create_twelve_cell_trace_png_bytes(),
            filename="twelve-cells.png",
        )
        layout = self.create_twelve_cell_layout_result()

        with patch(
            "ecg.services.image_pipeline.segment_ecg_lead_layout",
            return_value=layout,
        ) as layout_mock:
            result = run_ecg_image_pipeline(
                ecg_file,
                auto_detect_layout=True,
                lead_layout_format="standard_3x4",
                auto_extract_lead_signals=True,
            )

        layout_mock.assert_called_once_with(result.trace_candidates)
        self.assertTrue(result.leads_identified)
        self.assertTrue(result.per_lead_extracted)
        self.assertEqual(result.per_lead_signal_count, 12)
        self.assertTrue(result.lead_signal_extraction.complete_12_lead)
        self.assertEqual(
            result.per_lead_signal_names,
            (
                "I", "aVR", "V1", "V4",
                "II", "aVL", "V2", "V5",
                "III", "aVF", "V3", "V6",
            ),
        )
        self.assertEqual(len(result.per_lead_signals), 12)
        self.assertEqual(
            len({id(lead.reconstructed_signal)
                 for lead in result.per_lead_signals}),
            12,
        )
        for lead in result.per_lead_signals:
            with self.subTest(lead=lead.name):
                self.assertEqual(lead.sample_count, 20)
                self.assertEqual(lead.missing_count, 0)
                self.assertEqual(lead.coverage_ratio, 1.0)

        self.assertEqual(
            result.lead_signal_extraction.get_lead("I").x_positions_global,
            tuple(range(0, 20)),
        )
        self.assertEqual(
            result.lead_signal_extraction.get_lead("V6").x_positions_global,
            tuple(range(60, 80)),
        )
        # Old vertical-region signals and the new cell signals stay separate.
        self.assertEqual(
            len(result.lead_signals),
            result.region_count,
        )

    def test_pipeline_passes_exact_image_and_naming_result_to_extractor(self):
        ecg_file = self.create_image_file(
            self.create_twelve_cell_trace_png_bytes(),
            filename="twelve-cells-call.png",
        )
        layout = self.create_twelve_cell_layout_result()
        with (
            patch(
                "ecg.services.image_pipeline.segment_ecg_lead_layout",
                return_value=layout,
            ),
            patch(
                "ecg.services.image_pipeline.extract_ecg_lead_signals",
                wraps=extract_ecg_lead_signals,
            ) as extract_mock,
        ):
            result = run_ecg_image_pipeline(
                ecg_file,
                auto_detect_layout=True,
                lead_layout_format="standard_3x4",
                auto_extract_lead_signals=True,
            )

        extract_mock.assert_called_once_with(
            result.processed_image,
            result.lead_identification,
        )
        self.assertTrue(result.per_lead_extracted)
        self.assertEqual(result.per_lead_signal_count, 12)
        self.assertIs(
            result.per_lead_signals,
            result.lead_signal_extraction.leads,
        )

    def test_pipeline_wraps_independent_extraction_failure_safely(self):
        ecg_file = self.create_image_file(
            self.create_trace_png_bytes()
        )
        layout = self.create_lead_layout_result()
        with (
            patch(
                "ecg.services.image_pipeline.segment_ecg_lead_layout",
                return_value=layout,
            ),
            patch(
                "ecg.services.image_pipeline.extract_ecg_lead_signals",
                side_effect=ECGLeadSignalExtractionError(
                    "Synthetic lead extraction failure."
                ),
            ),
        ):
            with self.assertRaises(ECGImagePipelineError) as context:
                run_ecg_image_pipeline(
                    ecg_file,
                    auto_detect_layout=True,
                    lead_layout_format="standard_3x4",
                    auto_extract_lead_signals=True,
                )

        self.assertEqual(
            str(context.exception),
            "The independent ECG lead signals could not be extracted safely.",
        )
        self.assertIsInstance(
            context.exception.__cause__,
            ECGLeadSignalExtractionError,
        )

    def test_failed_identification_prevents_independent_extraction(self):
        ecg_file = self.create_image_file(
            self.create_trace_png_bytes()
        )
        valid_layout = self.create_lead_layout_result()
        incomplete_layout = replace(
            valid_layout,
            cells=valid_layout.cells[:-1],
        )
        with (
            patch(
                "ecg.services.image_pipeline.segment_ecg_lead_layout",
                return_value=incomplete_layout,
            ),
            patch(
                "ecg.services.image_pipeline.extract_ecg_lead_signals"
            ) as extract_mock,
        ):
            with self.assertRaises(ECGImagePipelineError) as context:
                run_ecg_image_pipeline(
                    ecg_file,
                    auto_detect_layout=True,
                    lead_layout_format="standard_3x4",
                    auto_extract_lead_signals=True,
                )

        extract_mock.assert_not_called()
        self.assertEqual(
            str(context.exception),
            "The ECG lead names could not be assigned safely.",
        )
        self.assertIsInstance(
            context.exception.__cause__,
            ECGLeadIdentificationError,
        )

    def test_independent_extraction_does_not_implicitly_calibrate_or_assess(self):
        ecg_file = self.create_image_file(
            self.create_twelve_cell_trace_png_bytes(),
            filename="twelve-cells-optional.png",
        )
        layout = self.create_twelve_cell_layout_result()
        with (
            patch(
                "ecg.services.image_pipeline.segment_ecg_lead_layout",
                return_value=layout,
            ),
            patch(
                "ecg.services.image_pipeline.detect_ecg_grid_scale"
            ) as grid_mock,
            patch(
                "ecg.services.image_pipeline.assess_ecg_processing_quality"
            ) as quality_mock,
        ):
            result = run_ecg_image_pipeline(
                ecg_file,
                auto_detect_layout=True,
                lead_layout_format="standard_3x4",
                auto_extract_lead_signals=True,
            )

        grid_mock.assert_not_called()
        quality_mock.assert_not_called()
        self.assertTrue(result.per_lead_extracted)
        self.assertEqual(result.per_lead_signal_count, 12)
        self.assertIsNone(result.grid_detection)
        self.assertIsNone(result.calibrated_signal)
        self.assertIsNone(result.quality_assessment)

    def test_independent_extraction_coexists_with_quality_and_calibration(self):
        ecg_file = self.create_image_file(
            self.create_twelve_cell_trace_png_bytes(),
            filename="twelve-cells-all-steps.png",
        )
        layout = self.create_twelve_cell_layout_result()
        grid_detection = self.create_grid_detection_result()
        calibrated_signal = self.create_calibrated_signal()
        with (
            patch(
                "ecg.services.image_pipeline.segment_ecg_lead_layout",
                return_value=layout,
            ),
            patch(
                "ecg.services.image_pipeline.detect_ecg_grid_scale",
                return_value=grid_detection,
            ) as grid_mock,
            patch(
                "ecg.services.image_pipeline.calibrate_reconstructed_signal",
                return_value=calibrated_signal,
            ) as calibration_mock,
        ):
            result = run_ecg_image_pipeline(
                ecg_file,
                auto_detect_layout=True,
                lead_layout_format="standard_3x4",
                auto_extract_lead_signals=True,
                auto_calibrate=True,
                auto_assess_quality=True,
            )

        grid_mock.assert_called_once_with(result.processed_image)
        self.assertEqual(
            calibration_mock.call_count,
            result.region_count + 1,
        )
        self.assertTrue(result.calibrated)
        self.assertTrue(result.quality_assessed)
        self.assertTrue(result.processing_usable)
        self.assertTrue(result.quality_assessment.layout_detected)
        self.assertTrue(result.quality_assessment.grid_detected)
        self.assertTrue(result.quality_assessment.calibrated)
        self.assertTrue(result.per_lead_extracted)
        self.assertEqual(result.per_lead_signal_count, 12)
        # Current calibration is still global + vertical regions only.
        # Per-cell calibration and per-cell quality are future stages.
