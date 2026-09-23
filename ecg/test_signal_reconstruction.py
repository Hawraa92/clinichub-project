import numpy as np

from django.test import SimpleTestCase, override_settings

from ecg.services.signal_reconstruction import (
    ECGSignalReconstructionError,
    reconstruct_ecg_signal,
)
from ecg.services.trace_extraction import ECGTraceCandidates


class ECGSignalReconstructionTests(SimpleTestCase):
    def create_candidates(
        self,
        candidate_mask,
    ):
        candidate_mask = np.asarray(
            candidate_mask,
            dtype=bool,
        )

        height, width = candidate_mask.shape

        return ECGTraceCandidates(
            width=width,
            height=height,
            threshold=120,
            candidate_mask=candidate_mask,
            foreground_ratio=(
                float(
                    np.count_nonzero(
                        candidate_mask
                    )
                )
                / candidate_mask.size
            ),
            removed_dense_rows=0,
            removed_dense_columns=0,
        )

    def test_reconstructs_complete_signal_path(self):
        candidate_mask = np.zeros(
            (8, 8),
            dtype=bool,
        )

        y_positions = [
            4,
            3,
            2,
            3,
            4,
            5,
            4,
            3,
        ]

        for column_index, row_index in enumerate(
            y_positions
        ):
            candidate_mask[
                row_index,
                column_index,
            ] = True

        candidates = self.create_candidates(
            candidate_mask
        )

        signal = reconstruct_ecg_signal(
            candidates
        )

        self.assertEqual(
            signal.width,
            8,
        )

        self.assertEqual(
            signal.height,
            8,
        )

        self.assertEqual(
            signal.sample_count,
            8,
        )

        self.assertEqual(
            signal.missing_count,
            0,
        )

        self.assertEqual(
            signal.coverage_ratio,
            1.0,
        )

        self.assertEqual(
            signal.interpolated_columns,
            0,
        )

        self.assertEqual(
            signal.baseline_y,
            3.5,
        )

        self.assertEqual(
            signal.x_positions,
            tuple(
                range(8)
            ),
        )

        self.assertEqual(
            signal.y_positions,
            (
                4.0,
                3.0,
                2.0,
                3.0,
                4.0,
                5.0,
                4.0,
                3.0,
            ),
        )

    def test_short_gap_is_interpolated(self):
        candidate_mask = np.zeros(
            (8, 6),
            dtype=bool,
        )

        candidate_mask[4, 0] = True
        candidate_mask[4, 1] = True

        candidate_mask[2, 4] = True
        candidate_mask[2, 5] = True

        candidates = self.create_candidates(
            candidate_mask
        )

        signal = reconstruct_ecg_signal(
            candidates
        )

        self.assertEqual(
            signal.interpolated_columns,
            2,
        )

        self.assertEqual(
            signal.sample_count,
            6,
        )

        self.assertEqual(
            signal.missing_count,
            0,
        )

        self.assertEqual(
            signal.coverage_ratio,
            1.0,
        )

        self.assertAlmostEqual(
            signal.y_positions[2],
            3.3333333333,
            places=6,
        )

        self.assertAlmostEqual(
            signal.y_positions[3],
            2.6666666667,
            places=6,
        )

    def test_insufficient_trace_coverage_is_rejected(self):
        candidate_mask = np.zeros(
            (8, 8),
            dtype=bool,
        )

        candidate_mask[
            4,
            0,
        ] = True

        candidates = self.create_candidates(
            candidate_mask
        )

        with self.assertRaises(
            ECGSignalReconstructionError
        ):
            reconstruct_ecg_signal(
                candidates
            )

    def test_reconstruction_respects_vertical_region(self):
        candidate_mask = np.zeros(
            (8, 6),
            dtype=bool,
        )

        for column_index in range(6):
            candidate_mask[
                0,
                column_index,
            ] = True

            candidate_mask[
                3,
                column_index,
            ] = True

        candidates = self.create_candidates(
            candidate_mask
        )

        signal = reconstruct_ecg_signal(
            candidates,
            region_top=2,
            region_bottom=6,
        )

        self.assertEqual(
            signal.region_top,
            2,
        )

        self.assertEqual(
            signal.region_bottom,
            6,
        )

        self.assertEqual(
            signal.y_positions,
            (
                3.0,
                3.0,
                3.0,
                3.0,
                3.0,
                3.0,
            ),
        )

    @override_settings(
        ECG_RECONSTRUCTION_MAX_GAP_COLUMNS=0
    )
    def test_gap_is_not_interpolated_when_disabled(self):
        candidate_mask = np.zeros(
            (8, 6),
            dtype=bool,
        )

        candidate_mask[4, 0] = True
        candidate_mask[4, 1] = True
        candidate_mask[2, 4] = True
        candidate_mask[2, 5] = True

        candidates = self.create_candidates(
            candidate_mask
        )

        signal = reconstruct_ecg_signal(
            candidates
        )

        self.assertEqual(
            signal.interpolated_columns,
            0,
        )

        self.assertEqual(
            signal.sample_count,
            4,
        )

        self.assertEqual(
            signal.missing_count,
            2,
        )

        self.assertIsNone(
            signal.y_positions[2]
        )

        self.assertIsNone(
            signal.y_positions[3]
        )

    def test_invalid_region_is_rejected(self):
        candidate_mask = np.zeros(
            (8, 6),
            dtype=bool,
        )

        candidate_mask[
            3,
            :,
        ] = True

        candidates = self.create_candidates(
            candidate_mask
        )

        with self.assertRaises(
            ECGSignalReconstructionError
        ):
            reconstruct_ecg_signal(
                candidates,
                region_top=6,
                region_bottom=2,
            )

    def test_mismatched_candidate_dimensions_are_rejected(self):
        candidate_mask = np.zeros(
            (4, 5),
            dtype=bool,
        )

        candidate_mask[
            2,
            :,
        ] = True

        candidates = ECGTraceCandidates(
            width=6,
            height=4,
            threshold=120,
            candidate_mask=candidate_mask,
            foreground_ratio=0.20,
            removed_dense_rows=0,
            removed_dense_columns=0,
        )

        with self.assertRaises(
            ECGSignalReconstructionError
        ):
            reconstruct_ecg_signal(
                candidates
            )