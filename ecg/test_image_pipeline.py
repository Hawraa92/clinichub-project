import io
import tempfile
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
from ecg.services.lead_segmentation import (
    ECGLeadLayoutCell,
    ECGLeadLayoutResult,
    ECGLeadRegion,
    ECGLeadSegmentationError,
)
from ecg.services.image_pipeline import (
    ECGImagePipelineError,
    run_ecg_image_pipeline,
)
from ecg.services.paper_detection import (
    ECGPaperDetectionError,
    ECGPaperDetectionResult,
)
from ecg.services.perspective import ECGImageQuadrilateral


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

    def create_trace_png_bytes(self):
        width = 20
        height = 12

        image = Image.new(
            "RGB",
            (width, height),
            color=(255, 255, 255),
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

    def test_pipeline_reconstructs_signal_from_ecg_image(self):
        ecg_file = self.create_image_file(
            self.create_trace_png_bytes()
        )

        result = run_ecg_image_pipeline(ecg_file)

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
            len(result.signal_values),
            20,
        )

        self.assertEqual(
            result.x_positions,
            tuple(range(20)),
        )

    def test_pipeline_exposes_each_processing_stage(self):
        ecg_file = self.create_image_file(
            self.create_trace_png_bytes()
        )

        result = run_ecg_image_pipeline(ecg_file)

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
            len(result.lead_signals),
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

        result = run_ecg_image_pipeline(ecg_file)

        self.assertEqual(
            result.region_count,
            1,
        )

        self.assertEqual(
            len(result.lead_signals),
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

        result = run_ecg_image_pipeline(ecg_file)

        self.assertEqual(
            result.region_count,
            2,
        )

        self.assertEqual(
            len(result.lead_signals),
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
            run_ecg_image_pipeline(ecg_file)

    def test_blank_image_is_wrapped_as_pipeline_error(self):
        ecg_file = self.create_image_file(
            self.create_blank_png_bytes()
        )

        with self.assertRaises(
            ECGImagePipelineError
        ):
            run_ecg_image_pipeline(ecg_file)

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

        result = run_ecg_image_pipeline(ecg_file)

        self.assertFalse(
            result.perspective_corrected
        )

        self.assertIsNone(
            result.perspective_correction
        )

        self.assertFalse(
            result.paper_detected
        )

        self.assertIsNone(
            result.paper_detection
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
            top_left=(0, 0),
            top_right=(19, 0),
            bottom_right=(19, 11),
            bottom_left=(0, 11),
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

        self.assertFalse(
            result.paper_detected
        )

        self.assertIsNone(
            result.paper_detection
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

        self.assertTrue(
            result.paper_detected
        )

        self.assertIs(
            result.paper_detection,
            detection_result,
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
            with self.assertRaises(
                ECGImagePipelineError
            ):
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

        self.assertTrue(
            result.perspective_corrected
        )

        self.assertFalse(
            result.paper_detected
        )

        self.assertIsNone(
            result.paper_detection
        )

        self.assertEqual(
            result.width,
            20,
        )

        self.assertEqual(
            result.height,
            12,
        )

    def test_pipeline_skips_2d_layout_detection_by_default(
        self,
    ):
        ecg_file = self.create_image_file(
            self.create_trace_png_bytes()
        )

        with patch(
            "ecg.services.image_pipeline.segment_ecg_lead_layout"
        ) as layout_mock:
            result = run_ecg_image_pipeline(
                ecg_file
            )

        layout_mock.assert_not_called()

        self.assertIsNone(
            result.lead_layout
        )

        self.assertFalse(
            result.layout_detected
        )

        self.assertEqual(
            result.layout_row_count,
            0,
        )

        self.assertEqual(
            result.layout_cell_count,
            0,
        )

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

        lead_layout = (
            self.create_lead_layout_result()
        )

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

        self.assertIs(
            result.lead_layout,
            lead_layout,
        )

        self.assertTrue(
            result.layout_detected
        )

        self.assertEqual(
            result.layout_row_count,
            3,
        )

        self.assertEqual(
            result.layout_cell_count,
            12,
        )

        self.assertEqual(
            result.layout_columns_per_row,
            (
                4,
                4,
                4,
            ),
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
            result = run_ecg_image_pipeline(
                ecg_file
            )

        grid_mock.assert_not_called()
        calibration_mock.assert_not_called()

        self.assertIsNone(
            result.grid_detection
        )

        self.assertIsNone(
            result.calibrated_signal
        )

        self.assertFalse(
            result.calibrated
        )

        for lead_signal in result.lead_signals:
            self.assertIsNone(
                lead_signal.calibrated_signal
            )

            self.assertFalse(
                lead_signal.calibrated
            )

    def test_pipeline_automatically_detects_grid_and_calibrates_signal(
        self,
    ):
        ecg_file = self.create_image_file(
            self.create_trace_png_bytes()
        )

        grid_detection = (
            self.create_grid_detection_result()
        )

        overall_calibrated_signal = (
            self.create_calibrated_signal()
        )

        lead_calibrated_signal = (
            self.create_calibrated_signal()
        )

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

        self.assertEqual(
            calibration_mock.call_count,
            2,
        )

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

        self.assertIs(
            result.grid_detection,
            grid_detection,
        )

        self.assertIs(
            result.calibrated_signal,
            overall_calibrated_signal,
        )

        self.assertTrue(
            result.calibrated
        )

        self.assertEqual(
            result.pixels_per_mm,
            5.0,
        )

        self.assertEqual(
            len(result.lead_signals),
            1,
        )

        self.assertTrue(
            result.lead_signals[0].calibrated
        )

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

        grid_detection = (
            self.create_grid_detection_result()
        )

        overall_calibrated_signal = (
            self.create_calibrated_signal()
        )

        first_lead_calibrated_signal = (
            self.create_calibrated_signal()
        )

        second_lead_calibrated_signal = (
            self.create_calibrated_signal()
        )

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

        self.assertEqual(
            result.region_count,
            2,
        )

        self.assertEqual(
            calibration_mock.call_count,
            3,
        )

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

        self.assertTrue(
            result.lead_signals[0].calibrated
        )

        self.assertTrue(
            result.lead_signals[1].calibrated
        )

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

        grid_detection = (
            self.create_grid_detection_result()
        )

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
            "The reconstructed ECG signal could not be calibrated safely.",
        )

    def test_pipeline_wraps_lead_calibration_failure_safely(
        self,
    ):
        ecg_file = self.create_image_file(
            self.create_trace_png_bytes()
        )

        grid_detection = (
            self.create_grid_detection_result()
        )

        overall_calibrated_signal = (
            self.create_calibrated_signal()
        )

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