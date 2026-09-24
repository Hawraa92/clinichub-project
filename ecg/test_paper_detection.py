import cv2
import numpy as np

from django.test import SimpleTestCase

from ecg.services.image_processing import (
    ProcessedECGImage,
)
from ecg.services.paper_detection import (
    ECGPaperDetectionError,
    ECGPaperDetectionResult,
    detect_ecg_paper_corners,
)
from ecg.services.perspective import (
    ECGImageQuadrilateral,
)


class ECGPaperDetectionTests(SimpleTestCase):
    def create_processed_image(
        self,
        grayscale,
    ):
        grayscale = np.asarray(
            grayscale
        )

        height, width = grayscale.shape

        return ProcessedECGImage(
            width=width,
            height=height,
            source_mode="L",
            grayscale=grayscale,
        )

    def assert_point_close(
        self,
        actual,
        expected,
        *,
        tolerance=3.0,
    ):
        self.assertAlmostEqual(
            actual[0],
            expected[0],
            delta=tolerance,
        )

        self.assertAlmostEqual(
            actual[1],
            expected[1],
            delta=tolerance,
        )

    def create_rectangular_paper_image(self):
        grayscale = np.full(
            (
                160,
                220,
            ),
            25,
            dtype=np.uint8,
        )

        cv2.rectangle(
            grayscale,
            (
                30,
                25,
            ),
            (
                190,
                135,
            ),
            240,
            thickness=-1,
        )

        return grayscale

    def create_skewed_paper_image(self):
        grayscale = np.full(
            (
                180,
                240,
            ),
            30,
            dtype=np.uint8,
        )

        paper_points = np.asarray(
            [
                [
                    30,
                    25,
                ],
                [
                    210,
                    20,
                ],
                [
                    220,
                    150,
                ],
                [
                    20,
                    155,
                ],
            ],
            dtype=np.int32,
        )

        cv2.fillConvexPoly(
            grayscale,
            paper_points,
            240,
        )

        return grayscale

    def test_detects_rectangular_ecg_paper(self):
        processed_image = self.create_processed_image(
            self.create_rectangular_paper_image()
        )

        result = detect_ecg_paper_corners(
            processed_image
        )

        self.assertIsInstance(
            result,
            ECGPaperDetectionResult,
        )

        self.assertIsInstance(
            result.corners,
            ECGImageQuadrilateral,
        )

        self.assert_point_close(
            result.top_left,
            (
                30,
                25,
            ),
        )

        self.assert_point_close(
            result.top_right,
            (
                190,
                25,
            ),
        )

        self.assert_point_close(
            result.bottom_right,
            (
                190,
                135,
            ),
        )

        self.assert_point_close(
            result.bottom_left,
            (
                30,
                135,
            ),
        )

        self.assertGreater(
            result.area_ratio,
            0.20,
        )

        self.assertGreaterEqual(
            result.candidate_count,
            1,
        )

    def test_detects_skewed_ecg_paper(self):
        processed_image = self.create_processed_image(
            self.create_skewed_paper_image()
        )

        result = detect_ecg_paper_corners(
            processed_image
        )

        self.assert_point_close(
            result.top_left,
            (
                30,
                25,
            ),
        )

        self.assert_point_close(
            result.top_right,
            (
                210,
                20,
            ),
        )

        self.assert_point_close(
            result.bottom_right,
            (
                220,
                150,
            ),
        )

        self.assert_point_close(
            result.bottom_left,
            (
                20,
                155,
            ),
        )

        self.assertGreater(
            result.contour_area,
            0.0,
        )

        self.assertGreater(
            result.area_ratio,
            0.20,
        )

    def test_selects_largest_valid_paper_candidate(self):
        grayscale = np.full(
            (
                160,
                280,
            ),
            20,
            dtype=np.uint8,
        )

        cv2.rectangle(
            grayscale,
            (
                20,
                20,
            ),
            (
                175,
                135,
            ),
            240,
            thickness=-1,
        )

        cv2.rectangle(
            grayscale,
            (
                205,
                35,
            ),
            (
                260,
                100,
            ),
            240,
            thickness=-1,
        )

        processed_image = self.create_processed_image(
            grayscale
        )

        result = detect_ecg_paper_corners(
            processed_image,
            min_area_ratio=0.05,
        )

        self.assert_point_close(
            result.top_left,
            (
                20,
                20,
            ),
        )

        self.assert_point_close(
            result.top_right,
            (
                175,
                20,
            ),
        )

        self.assert_point_close(
            result.bottom_right,
            (
                175,
                135,
            ),
        )

        self.assert_point_close(
            result.bottom_left,
            (
                20,
                135,
            ),
        )

        self.assertGreaterEqual(
            result.candidate_count,
            2,
        )

    def test_blank_image_is_rejected(self):
        grayscale = np.full(
            (
                160,
                220,
            ),
            255,
            dtype=np.uint8,
        )

        processed_image = self.create_processed_image(
            grayscale
        )

        with self.assertRaises(
            ECGPaperDetectionError
        ):
            detect_ecg_paper_corners(
                processed_image
            )

    def test_small_quadrilateral_below_area_threshold_is_rejected(self):
        grayscale = np.full(
            (
                200,
                200,
            ),
            20,
            dtype=np.uint8,
        )

        cv2.rectangle(
            grayscale,
            (
                80,
                80,
            ),
            (
                120,
                120,
            ),
            240,
            thickness=-1,
        )

        processed_image = self.create_processed_image(
            grayscale
        )

        with self.assertRaises(
            ECGPaperDetectionError
        ):
            detect_ecg_paper_corners(
                processed_image
            )

    def test_invalid_processed_image_is_rejected(self):
        with self.assertRaises(
            ECGPaperDetectionError
        ):
            detect_ecg_paper_corners(
                object()
            )

    def test_image_that_is_too_small_is_rejected(self):
        processed_image = ProcessedECGImage(
            width=4,
            height=4,
            source_mode="L",
            grayscale=np.zeros(
                (
                    4,
                    4,
                ),
                dtype=np.uint8,
            ),
        )

        with self.assertRaises(
            ECGPaperDetectionError
        ):
            detect_ecg_paper_corners(
                processed_image
            )

    def test_invalid_min_area_ratio_is_rejected(self):
        processed_image = self.create_processed_image(
            self.create_rectangular_paper_image()
        )

        for invalid_value in (
            0,
            -0.1,
            1.1,
            True,
            float("nan"),
            float("inf"),
        ):
            with self.subTest(
                invalid_value=invalid_value
            ):
                with self.assertRaises(
                    ECGPaperDetectionError
                ):
                    detect_ecg_paper_corners(
                        processed_image,
                        min_area_ratio=invalid_value,
                    )

    def test_invalid_approximation_ratio_is_rejected(self):
        processed_image = self.create_processed_image(
            self.create_rectangular_paper_image()
        )

        for invalid_value in (
            0,
            -0.1,
            1.0,
            True,
            float("nan"),
            float("inf"),
        ):
            with self.subTest(
                invalid_value=invalid_value
            ):
                with self.assertRaises(
                    ECGPaperDetectionError
                ):
                    detect_ecg_paper_corners(
                        processed_image,
                        approx_epsilon_ratio=invalid_value,
                    )