import numpy as np

from django.test import SimpleTestCase

from ecg.services.image_processing import ProcessedECGImage
from ecg.services.perspective import (
    DEFAULT_ECG_PERSPECTIVE_MAX_PIXELS,
    ECGImageQuadrilateral,
    ECGPerspectiveCorrectionError,
    RectifiedECGImage,
    _calculate_output_dimensions,
    correct_ecg_perspective,
)


class ECGPerspectiveCorrectionTests(SimpleTestCase):

    def _make_processed_image(
        self,
        *,
        width=8,
        height=6,
        grayscale=None,
    ):
        if grayscale is None:
            grayscale = np.arange(
                width * height,
                dtype=np.uint8,
            ).reshape(
                height,
                width,
            )

        return ProcessedECGImage(
            width=width,
            height=height,
            source_mode="L",
            grayscale=grayscale,
        )

    def test_identity_rectangle_preserves_dimensions_and_pixels(self):
        """
        A rectangular ECG image whose supplied corners already match
        the image boundaries should remain unchanged.

        This also verifies the +1 endpoint-pixel correction:
        coordinates 0..7 represent 8 pixels and
        coordinates 0..5 represent 6 pixels.
        """

        processed_image = self._make_processed_image(
            width=8,
            height=6,
        )

        corners = ECGImageQuadrilateral(
            top_left=(0.0, 0.0),
            top_right=(7.0, 0.0),
            bottom_right=(7.0, 5.0),
            bottom_left=(0.0, 5.0),
        )

        result = correct_ecg_perspective(
            processed_image,
            corners=corners,
        )

        self.assertIsInstance(
            result,
            RectifiedECGImage,
        )

        self.assertEqual(
            result.width,
            8,
        )

        self.assertEqual(
            result.height,
            6,
        )

        self.assertEqual(
            result.shape,
            (6, 8),
        )

        self.assertEqual(
            result.pixel_count,
            48,
        )

        np.testing.assert_array_equal(
            result.grayscale,
            processed_image.grayscale,
        )

    def test_output_dimensions_include_endpoint_pixel(self):
        """
        Pixel coordinates are inclusive endpoints.

        x = 0..99 means 100 pixels.
        y = 0..49 means 50 pixels.
        """

        corners = ECGImageQuadrilateral(
            top_left=(0.0, 0.0),
            top_right=(99.0, 0.0),
            bottom_right=(99.0, 49.0),
            bottom_left=(0.0, 49.0),
        )

        width, height = _calculate_output_dimensions(
            corners
        )

        self.assertEqual(
            width,
            100,
        )

        self.assertEqual(
            height,
            50,
        )

    def test_perspective_correction_returns_expected_shape(self):
        """
        A valid trapezoid should be rectified into a rectangular
        grayscale image with calculated output dimensions.
        """

        grayscale = np.arange(
            100,
            dtype=np.uint8,
        ).reshape(
            10,
            10,
        )

        processed_image = self._make_processed_image(
            width=10,
            height=10,
            grayscale=grayscale,
        )

        corners = ECGImageQuadrilateral(
            top_left=(1.0, 1.0),
            top_right=(8.0, 0.0),
            bottom_right=(9.0, 8.0),
            bottom_left=(0.0, 9.0),
        )

        result = correct_ecg_perspective(
            processed_image,
            corners=corners,
        )

        self.assertIsInstance(
            result,
            RectifiedECGImage,
        )

        self.assertEqual(
            result.width,
            10,
        )

        self.assertEqual(
            result.height,
            9,
        )

        self.assertEqual(
            result.grayscale.shape,
            (9, 10),
        )

        self.assertEqual(
            result.grayscale.dtype,
            np.uint8,
        )

    def test_homography_is_finite_three_by_three_matrix(self):
        processed_image = self._make_processed_image(
            width=10,
            height=10,
        )

        corners = ECGImageQuadrilateral(
            top_left=(1.0, 1.0),
            top_right=(8.0, 0.0),
            bottom_right=(9.0, 8.0),
            bottom_left=(0.0, 9.0),
        )

        result = correct_ecg_perspective(
            processed_image,
            corners=corners,
        )

        self.assertEqual(
            result.homography.shape,
            (3, 3),
        )

        self.assertTrue(
            np.all(
                np.isfinite(
                    result.homography
                )
            )
        )

    def test_source_corners_are_preserved_in_result(self):
        processed_image = self._make_processed_image(
            width=8,
            height=6,
        )

        corners = ECGImageQuadrilateral(
            top_left=(0.0, 0.0),
            top_right=(7.0, 0.0),
            bottom_right=(7.0, 5.0),
            bottom_left=(0.0, 5.0),
        )

        result = correct_ecg_perspective(
            processed_image,
            corners=corners,
        )

        self.assertEqual(
            result.source_corners,
            corners,
        )

    def test_invalid_processed_image_is_rejected(self):
        corners = ECGImageQuadrilateral(
            top_left=(0.0, 0.0),
            top_right=(7.0, 0.0),
            bottom_right=(7.0, 5.0),
            bottom_left=(0.0, 5.0),
        )

        with self.assertRaisesRegex(
            ECGPerspectiveCorrectionError,
            "Expected ProcessedECGImage",
        ):
            correct_ecg_perspective(
                object(),
                corners=corners,
            )

    def test_duplicate_corners_are_rejected(self):
        processed_image = self._make_processed_image(
            width=10,
            height=10,
        )

        corners = ECGImageQuadrilateral(
            top_left=(0.0, 0.0),
            top_right=(9.0, 0.0),
            bottom_right=(9.0, 9.0),
            bottom_left=(9.0, 9.0),
        )

        with self.assertRaisesRegex(
            ECGPerspectiveCorrectionError,
            "four distinct points",
        ):
            correct_ecg_perspective(
                processed_image,
                corners=corners,
            )

    def test_corner_outside_image_width_is_rejected(self):
        processed_image = self._make_processed_image(
            width=10,
            height=10,
        )

        corners = ECGImageQuadrilateral(
            top_left=(0.0, 0.0),
            top_right=(10.0, 0.0),
            bottom_right=(9.0, 9.0),
            bottom_left=(0.0, 9.0),
        )

        with self.assertRaisesRegex(
            ECGPerspectiveCorrectionError,
            "outside the image width",
        ):
            correct_ecg_perspective(
                processed_image,
                corners=corners,
            )

    def test_corner_outside_image_height_is_rejected(self):
        processed_image = self._make_processed_image(
            width=10,
            height=10,
        )

        corners = ECGImageQuadrilateral(
            top_left=(0.0, 0.0),
            top_right=(9.0, 0.0),
            bottom_right=(9.0, 10.0),
            bottom_left=(0.0, 9.0),
        )

        with self.assertRaisesRegex(
            ECGPerspectiveCorrectionError,
            "outside the image height",
        ):
            correct_ecg_perspective(
                processed_image,
                corners=corners,
            )

    def test_non_finite_corner_coordinate_is_rejected(self):
        processed_image = self._make_processed_image(
            width=10,
            height=10,
        )

        corners = ECGImageQuadrilateral(
            top_left=(0.0, 0.0),
            top_right=(9.0, 0.0),
            bottom_right=(9.0, float("inf")),
            bottom_left=(0.0, 9.0),
        )

        with self.assertRaisesRegex(
            ECGPerspectiveCorrectionError,
            "finite numbers",
        ):
            correct_ecg_perspective(
                processed_image,
                corners=corners,
            )

    def test_boolean_corner_coordinate_is_rejected(self):
        processed_image = self._make_processed_image(
            width=10,
            height=10,
        )

        corners = ECGImageQuadrilateral(
            top_left=(False, 0.0),
            top_right=(9.0, 0.0),
            bottom_right=(9.0, 9.0),
            bottom_left=(0.0, 9.0),
        )

        with self.assertRaisesRegex(
            ECGPerspectiveCorrectionError,
            "finite numbers",
        ):
            correct_ecg_perspective(
                processed_image,
                corners=corners,
            )

    def test_bad_corner_shape_is_rejected(self):
        processed_image = self._make_processed_image(
            width=10,
            height=10,
        )

        corners = ECGImageQuadrilateral(
            top_left=(0.0,),
            top_right=(9.0, 0.0),
            bottom_right=(9.0, 9.0),
            bottom_left=(0.0, 9.0),
        )

        with self.assertRaisesRegex(
            ECGPerspectiveCorrectionError,
            "exactly two coordinates",
        ):
            correct_ecg_perspective(
                processed_image,
                corners=corners,
            )

    def test_non_convex_or_bad_perimeter_order_is_rejected(self):
        """
        Bow-tie ordering is not a valid convex quadrilateral.
        """

        processed_image = self._make_processed_image(
            width=10,
            height=10,
        )

        corners = ECGImageQuadrilateral(
            top_left=(0.0, 0.0),
            top_right=(9.0, 0.0),
            bottom_right=(0.0, 9.0),
            bottom_left=(9.0, 9.0),
        )

        with self.assertRaisesRegex(
            ECGPerspectiveCorrectionError,
            "convex quadrilateral",
        ):
            correct_ecg_perspective(
                processed_image,
                corners=corners,
            )

    def test_degenerate_quadrilateral_is_rejected(self):
        """
        Three consecutive collinear points cannot form
        a valid perspective quadrilateral.
        """

        processed_image = self._make_processed_image(
            width=10,
            height=10,
        )

        corners = ECGImageQuadrilateral(
            top_left=(0.0, 0.0),
            top_right=(3.0, 0.0),
            bottom_right=(6.0, 0.0),
            bottom_left=(0.0, 9.0),
        )

        with self.assertRaisesRegex(
            ECGPerspectiveCorrectionError,
            "non-degenerate quadrilateral",
        ):
            correct_ecg_perspective(
                processed_image,
                corners=corners,
            )

    def test_excessive_output_pixel_count_is_rejected(self):
        """
        Test the safety limit without allocating a huge image.
        """

        corners = ECGImageQuadrilateral(
            top_left=(0.0, 0.0),
            top_right=(10000.0, 0.0),
            bottom_right=(10000.0, 5000.0),
            bottom_left=(0.0, 5000.0),
        )

        expected_pixel_count = (
            10001
            * 5001
        )

        self.assertGreater(
            expected_pixel_count,
            DEFAULT_ECG_PERSPECTIVE_MAX_PIXELS,
        )

        with self.assertRaisesRegex(
            ECGPerspectiveCorrectionError,
            "safe pixel limit",
        ):
            _calculate_output_dimensions(
                corners
            )

    def test_output_is_uint8(self):
        processed_image = self._make_processed_image(
            width=8,
            height=6,
        )

        corners = ECGImageQuadrilateral(
            top_left=(0.0, 0.0),
            top_right=(7.0, 0.0),
            bottom_right=(7.0, 5.0),
            bottom_left=(0.0, 5.0),
        )

        result = correct_ecg_perspective(
            processed_image,
            corners=corners,
        )

        self.assertEqual(
            result.grayscale.dtype,
            np.uint8,
        )