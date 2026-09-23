import numpy as np

from django.test import SimpleTestCase, override_settings

from ecg.services.image_processing import ProcessedECGImage
from ecg.services.trace_extraction import (
    ECGTraceExtractionError,
    extract_trace_candidates,
)


class ECGTraceExtractionTests(SimpleTestCase):
    def create_processed_image(
        self,
        grayscale,
    ):
        grayscale = np.asarray(
            grayscale,
            dtype=np.uint8,
        )

        height, width = grayscale.shape

        return ProcessedECGImage(
            width=width,
            height=height,
            source_mode="L",
            grayscale=grayscale,
        )

    def test_dark_pixels_are_detected_as_trace_candidates(self):
        grayscale = np.full(
            (6, 6),
            255,
            dtype=np.uint8,
        )

        grayscale[2, 1] = 20
        grayscale[2, 2] = 40
        grayscale[3, 3] = 60

        processed = self.create_processed_image(
            grayscale
        )

        candidates = extract_trace_candidates(
            processed
        )

        self.assertEqual(
            candidates.width,
            6,
        )

        self.assertEqual(
            candidates.height,
            6,
        )

        self.assertEqual(
            candidates.shape,
            (
                6,
                6,
            ),
        )

        self.assertEqual(
            candidates.threshold,
            120,
        )

        self.assertEqual(
            candidates.candidate_pixel_count,
            3,
        )

        self.assertTrue(
            candidates.candidate_mask[
                2,
                1,
            ]
        )

        self.assertFalse(
            candidates.candidate_mask[
                0,
                0,
            ]
        )

    def test_dense_grid_row_is_removed(self):
        grayscale = np.full(
            (10, 10),
            255,
            dtype=np.uint8,
        )

        grayscale[5, :] = 20
        grayscale[1, 1] = 20

        processed = self.create_processed_image(
            grayscale
        )

        candidates = extract_trace_candidates(
            processed
        )

        self.assertEqual(
            candidates.removed_dense_rows,
            1,
        )

        self.assertEqual(
            candidates.removed_dense_columns,
            0,
        )

        self.assertEqual(
            candidates.candidate_pixel_count,
            1,
        )

        self.assertTrue(
            candidates.candidate_mask[
                1,
                1,
            ]
        )

        self.assertFalse(
            np.any(
                candidates.candidate_mask[
                    5,
                    :,
                ]
            )
        )

    def test_blank_image_is_rejected(self):
        grayscale = np.full(
            (10, 10),
            255,
            dtype=np.uint8,
        )

        processed = self.create_processed_image(
            grayscale
        )

        with self.assertRaises(
            ECGTraceExtractionError
        ):
            extract_trace_candidates(
                processed
            )

    @override_settings(
        ECG_TRACE_GRID_DENSITY=1.0,
        ECG_TRACE_MAX_FOREGROUND_RATIO=0.50,
    )
    def test_excessive_foreground_is_rejected(self):
        grayscale = np.full(
            (10, 10),
            255,
            dtype=np.uint8,
        )

        for row_index in range(10):
            start = row_index

            for offset in range(6):
                column_index = (
                    start + offset
                ) % 10

                grayscale[
                    row_index,
                    column_index,
                ] = 20

        processed = self.create_processed_image(
            grayscale
        )

        with self.assertRaises(
            ECGTraceExtractionError
        ):
            extract_trace_candidates(
                processed
            )

    @override_settings(
        ECG_TRACE_DARK_THRESHOLD=300
    )
    def test_invalid_dark_threshold_is_rejected(self):
        grayscale = np.full(
            (6, 6),
            255,
            dtype=np.uint8,
        )

        grayscale[2, 2] = 20

        processed = self.create_processed_image(
            grayscale
        )

        with self.assertRaises(
            ECGTraceExtractionError
        ):
            extract_trace_candidates(
                processed
            )

    def test_mismatched_image_dimensions_are_rejected(self):
        grayscale = np.full(
            (4, 5),
            255,
            dtype=np.uint8,
        )

        grayscale[2, 2] = 20

        processed = ProcessedECGImage(
            width=6,
            height=4,
            source_mode="L",
            grayscale=grayscale,
        )

        with self.assertRaises(
            ECGTraceExtractionError
        ):
            extract_trace_candidates(
                processed
            )