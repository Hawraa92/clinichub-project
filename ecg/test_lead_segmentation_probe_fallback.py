"""
ECG Lead Segmentation - Horizontal-Probe Fallback Tests.

Purpose:
    Protect the standard_3x4 overlap-recovery behavior against
    future regressions.

These tests use synthetic candidate masks.

They do not depend on real ECG images, reference annotations,
waveform interpretation, or clinical diagnoses.

The horizontal-probe fallback must:
    1. Recover three nominal rows when one column connects
       two otherwise separate signal rows.
    2. Preserve the complete original candidate mask.
    3. Reject ambiguous cases when fewer than three
       independent probes establish three signal rows.

The fallback applies only to the explicit standard_3x4 profile.
"""

import numpy as np

from django.test import SimpleTestCase, override_settings

from ecg.services.lead_segmentation import (
    ECGLeadSegmentationError,
    segment_ecg_lead_layout,
    segment_ecg_lead_regions,
)

from ecg.services.trace_extraction import ECGTraceCandidates


@override_settings(
    ECG_LEAD_SEGMENTATION_MIN_ACTIVE_PIXELS=3,
    ECG_LEAD_SEGMENTATION_MAX_GAP_ROWS=0,
    ECG_LEAD_SEGMENTATION_PADDING_ROWS=0,
    ECG_LEAD_SEGMENTATION_MAX_REGIONS=10,
)
class ECGStandard3x4ProbeFallbackTests(SimpleTestCase):

    # =====================================================
    # 1. SYNTHETIC TEST HELPERS
    # =====================================================

    def make_candidates(self, mask):
        """
        Construct valid trace candidates from a Boolean mask.
        """

        mask = np.asarray(mask, dtype=bool)

        height, width = mask.shape

        candidate_pixel_count = int(
            np.count_nonzero(mask)
        )

        foreground_ratio = (
            candidate_pixel_count / mask.size
        )

        return ECGTraceCandidates(
            width=width,
            height=height,
            threshold=120,
            candidate_mask=mask,
            foreground_ratio=foreground_ratio,
            removed_dense_rows=0,
            removed_dense_columns=0,
        )

    def make_overlap_mask(
        self,
        *,
        contaminated_columns=(4,),
    ):
        """
        Construct a synthetic standard 3x4 candidate mask.

        Normal layout:
            Three separated horizontal signal rows.
            Four separated signal columns.

        Each contaminated column receives a vertical bridge
        connecting the first and second signal rows.

        The bridge causes the full-width vertical detector
        to observe two regions instead of three.

        Column numbering is one-based.
        """

        mask = np.zeros(
            (60, 120),
            dtype=bool,
        )

        row_ranges = (
            (4, 12),
            (26, 34),
            (48, 56),
        )

        column_ranges = (
            (4, 24),
            (32, 52),
            (60, 80),
            (88, 108),
        )

        # Create the original twelve signal blocks.

        for top, bottom in row_ranges:

            for left, right in column_ranges:

                mask[
                    top:bottom,
                    left:right,
                ] = True

        # Add vertical bridges between rows 1 and 2.
        #
        # Five active pixels per bridge row ensure that
        # the bridge exceeds the configured row threshold.

        for column_number in contaminated_columns:

            left, right = column_ranges[
                column_number - 1
            ]

            bridge_left = left + 7
            bridge_right = bridge_left + 5

            mask[
                12:26,
                bridge_left:bridge_right,
            ] = True

        return mask

    # =====================================================
    # TEST 1
    # Recover three rows when the fourth column overlaps.
    # =====================================================

    def test_recovers_three_rows_with_one_contaminated_probe(self):
        """
        The fourth column connects rows 1 and 2.

        The generic full-width detector observes two regions.

        The explicit standard_3x4 profile must recover three
        nominal rows using the three uncontaminated probes.

        All four columns and all original candidate pixels
        must remain represented in the final layout.
        """

        mask = self.make_overlap_mask(
            contaminated_columns=(4,),
        )

        original_mask = mask.copy()

        original_candidate_count = int(
            np.count_nonzero(mask)
        )

        candidates = self.make_candidates(mask)

        # Confirm that the synthetic mask reproduces
        # the intended full-width row-merging problem.

        generic_regions = segment_ecg_lead_regions(
            candidates
        )

        self.assertEqual(
            generic_regions.region_count,
            2,
        )

        # Explicitly activate the optional recovery profile.

        result = segment_ecg_lead_layout(
            candidates,
            layout_profile="standard_3x4",
        )

        # Confirm successful structural recovery.

        self.assertEqual(
            result.row_count,
            3,
        )

        self.assertEqual(
            result.cell_count,
            12,
        )

        self.assertEqual(
            result.columns_per_row,
            (4, 4, 4),
        )

        # Verify all twelve row/column positions.

        expected_positions = tuple(
            (row, column)
            for row in range(1, 4)
            for column in range(1, 5)
        )

        actual_positions = tuple(
            (cell.row_index, cell.column_index)
            for cell in result.cells
        )

        self.assertEqual(
            actual_positions,
            expected_positions,
        )

        # The contaminated fourth column must remain present
        # in all three output rows.

        fourth_column_cells = tuple(
            cell
            for cell in result.cells
            if cell.column_index == 4
        )

        self.assertEqual(
            len(fourth_column_cells),
            3,
        )

        for cell in fourth_column_cells:

            self.assertGreater(
                cell.candidate_pixel_count,
                0,
            )

        # Verify that the input mask was not modified.

        np.testing.assert_array_equal(
            candidates.candidate_mask,
            original_mask,
        )

        # All original candidate pixels must be accounted for
        # by the twelve non-overlapping nominal cells.

        detected_candidate_count = sum(
            cell.candidate_pixel_count
            for cell in result.cells
        )

        self.assertEqual(
            detected_candidate_count,
            original_candidate_count,
        )

    # =====================================================
    # TEST 2
    # Reject recovery when fewer than three probes agree.
    # =====================================================

    def test_rejects_when_only_two_probes_are_valid(self):
        """
        Connect rows 1 and 2 in columns 2 and 4.

        This produces two contaminated horizontal probes.

        Only the first and third probes can independently
        identify three signal rows.

        The fallback must reject the ambiguous layout
        rather than force a nominal 3x4 result.
        """

        mask = self.make_overlap_mask(
            contaminated_columns=(2, 4),
        )

        candidates = self.make_candidates(mask)

        # Confirm the full-width detector sees two regions.

        generic_regions = segment_ecg_lead_regions(
            candidates
        )

        self.assertEqual(
            generic_regions.region_count,
            2,
        )

        # Recovery must not succeed without three
        # independently valid horizontal probes.

        with self.assertRaisesRegex(
            ECGLeadSegmentationError,
            "requires three signal rows",
        ) as caught:

            segment_ecg_lead_layout(
                candidates,
                layout_profile="standard_3x4",
            )

        # Confirm that the rejection originated from
        # insufficient horizontal-probe consensus.

        self.assertIsInstance(
            caught.exception.__cause__,
            ECGLeadSegmentationError,
        )

        self.assertIn(
            "at least three horizontal probes",
            str(caught.exception.__cause__),
        )