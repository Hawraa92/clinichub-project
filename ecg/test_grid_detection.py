import numpy as np

from django.test import SimpleTestCase

from ecg.services.grid_detection import (
    ECGGridDetectionError,
    detect_ecg_grid_scale,
)
from ecg.services.image_processing import (
    ProcessedECGImage,
)


class ECGGridDetectionTests(SimpleTestCase):
    def make_grid_image(
        self,
        *,
        width=40,
        height=40,
        x_spacing=5,
        y_spacing=5,
        x_start=2,
        y_start=2,
        background=255,
        grid_intensity=210,
    ):
        grayscale = np.full(
            (
                height,
                width,
            ),
            background,
            dtype=np.uint8,
        )

        for x_position in range(
            x_start,
            width,
            x_spacing,
        ):
            grayscale[
                :,
                x_position,
            ] = grid_intensity

        for y_position in range(
            y_start,
            height,
            y_spacing,
        ):
            grayscale[
                y_position,
                :,
            ] = grid_intensity

        return ProcessedECGImage(
            width=width,
            height=height,
            source_mode="L",
            grayscale=grayscale,
        )

    def test_detects_regular_ecg_grid_scale(self):
        processed_image = self.make_grid_image(
            x_spacing=5,
            y_spacing=5,
        )

        result = detect_ecg_grid_scale(
            processed_image
        )

        self.assertAlmostEqual(
            result.pixels_per_mm,
            5.0,
        )

        self.assertAlmostEqual(
            result.x_spacing_pixels,
            5.0,
        )

        self.assertAlmostEqual(
            result.y_spacing_pixels,
            5.0,
        )

        self.assertAlmostEqual(
            result.axis_difference_ratio,
            0.0,
        )

        self.assertGreaterEqual(
            result.x_line_count,
            4,
        )

        self.assertGreaterEqual(
            result.y_line_count,
            4,
        )

    def test_sparse_dark_trace_does_not_change_grid_scale(self):
        processed_image = self.make_grid_image(
            x_spacing=5,
            y_spacing=5,
        )

        grayscale = processed_image.grayscale.copy()

        for x_position in range(
            processed_image.width
        ):
            y_position = (
                20
                + (
                    x_position
                    % 3
                )
            )

            grayscale[
                y_position,
                x_position,
            ] = 0

        processed_image = ProcessedECGImage(
            width=processed_image.width,
            height=processed_image.height,
            source_mode=processed_image.source_mode,
            grayscale=grayscale,
        )

        result = detect_ecg_grid_scale(
            processed_image
        )

        self.assertAlmostEqual(
            result.pixels_per_mm,
            5.0,
        )

    def test_blank_image_is_rejected(self):
        grayscale = np.full(
            (
                40,
                40,
            ),
            255,
            dtype=np.uint8,
        )

        processed_image = ProcessedECGImage(
            width=40,
            height=40,
            source_mode="L",
            grayscale=grayscale,
        )

        with self.assertRaises(
            ECGGridDetectionError
        ):
            detect_ecg_grid_scale(
                processed_image
            )

    def test_inconsistent_axis_scales_are_rejected(self):
        processed_image = self.make_grid_image(
            width=50,
            height=50,
            x_spacing=5,
            y_spacing=8,
        )

        with self.assertRaises(
            ECGGridDetectionError
        ):
            detect_ecg_grid_scale(
                processed_image
            )

    def test_too_few_grid_lines_are_rejected(self):
        processed_image = self.make_grid_image(
            width=20,
            height=20,
            x_spacing=10,
            y_spacing=10,
        )

        with self.assertRaises(
            ECGGridDetectionError
        ):
            detect_ecg_grid_scale(
                processed_image
            )

    def test_mismatched_image_dimensions_are_rejected(self):
        grayscale = np.full(
            (
                40,
                40,
            ),
            255,
            dtype=np.uint8,
        )

        processed_image = ProcessedECGImage(
            width=41,
            height=40,
            source_mode="L",
            grayscale=grayscale,
        )

        with self.assertRaises(
            ECGGridDetectionError
        ):
            detect_ecg_grid_scale(
                processed_image
            )

    def test_image_that_is_too_small_is_rejected(self):
        grayscale = np.full(
            (
                9,
                9,
            ),
            255,
            dtype=np.uint8,
        )

        processed_image = ProcessedECGImage(
            width=9,
            height=9,
            source_mode="L",
            grayscale=grayscale,
        )

        with self.assertRaises(
            ECGGridDetectionError
        ):
            detect_ecg_grid_scale(
                processed_image
            )

    def test_invalid_detection_parameters_are_rejected(self):
        processed_image = self.make_grid_image()

        invalid_parameters = (
            {
                "min_contrast": 0,
            },
            {
                "peak_ratio": 1.5,
            },
            {
                "min_line_count": 2,
            },
            {
                "min_spacing_pixels": 0,
            },
            {
                "axis_tolerance_ratio": 1.5,
            },
            {
                "interval_tolerance_ratio": 1.5,
            },
        )

        for parameters in invalid_parameters:
            with self.subTest(
                parameters=parameters
            ):
                with self.assertRaises(
                    ECGGridDetectionError
                ):
                    detect_ecg_grid_scale(
                        processed_image,
                        **parameters,
                    )
