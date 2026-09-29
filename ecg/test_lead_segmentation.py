
import numpy as np

from django.test import SimpleTestCase, override_settings

from ecg.services.lead_segmentation import (
    ECGLeadSegmentationError,
    segment_ecg_lead_layout,
    segment_ecg_lead_regions,
)

from ecg.services.trace_extraction import ECGTraceCandidates


class ECGLeadSegmentationTests(SimpleTestCase):

    # =====================================================
    # Test Helpers
    # =====================================================

    def make_candidates(self, mask):

        mask = np.asarray(mask, dtype=bool)

        height, width = mask.shape

        candidate_pixel_count = int(
            np.count_nonzero(mask)
        )

        foreground_ratio = candidate_pixel_count / mask.size

        return ECGTraceCandidates(
            width=width,
            height=height,
            threshold=120,
            candidate_mask=mask,
            foreground_ratio=foreground_ratio,
            removed_dense_rows=0,
            removed_dense_columns=0,
        )

    def make_three_by_four_layout_candidates(self):

        mask = np.zeros((15, 23), dtype=bool)

        row_ranges = (
            (1, 3),
            (6, 8),
            (11, 13),
        )

        column_ranges = (
            (1, 4),
            (6, 9),
            (11, 14),
            (16, 19),
        )

        for top, bottom in row_ranges:
            for left, right in column_ranges:
                mask[top:bottom, left:right] = True

        return self.make_candidates(mask)

    # =====================================================
    # ORIGINAL TESTS - Vertical Segmentation
    # =====================================================

    @override_settings(
        ECG_LEAD_SEGMENTATION_MAX_GAP_ROWS=0,
        ECG_LEAD_SEGMENTATION_PADDING_ROWS=0,
    )
    def test_separates_distinct_vertical_regions(self):

        mask = np.zeros((12, 10), dtype=bool)

        mask[1:3, 1:9] = True
        mask[7:9, 1:9] = True

        candidates = self.make_candidates(mask)

        result = segment_ecg_lead_regions(candidates)

        self.assertEqual(result.region_count, 2)

        first = result.regions[0]
        second = result.regions[1]

        self.assertEqual(
            (first.top, first.bottom),
            (1, 3),
        )

        self.assertEqual(
            (second.top, second.bottom),
            (7, 9),
        )

    @override_settings(
        ECG_LEAD_SEGMENTATION_MAX_GAP_ROWS=1,
        ECG_LEAD_SEGMENTATION_PADDING_ROWS=0,
    )
    def test_small_row_gap_is_grouped_into_one_region(self):

        mask = np.zeros((10, 8), dtype=bool)

        mask[2, 1:7] = True
        mask[4, 1:7] = True

        candidates = self.make_candidates(mask)

        result = segment_ecg_lead_regions(candidates)

        self.assertEqual(result.region_count, 1)

        region = result.regions[0]

        self.assertEqual(region.active_top, 2)
        self.assertEqual(region.active_bottom, 5)

    @override_settings(
        ECG_LEAD_SEGMENTATION_MAX_GAP_ROWS=0,
        ECG_LEAD_SEGMENTATION_PADDING_ROWS=2,
    )
    def test_padding_is_applied_without_exceeding_image(self):

        mask = np.zeros((10, 8), dtype=bool)

        mask[1, 1:7] = True
        mask[8, 1:7] = True

        candidates = self.make_candidates(mask)

        result = segment_ecg_lead_regions(candidates)

        first = result.regions[0]
        second = result.regions[1]

        self.assertEqual(first.top, 0)
        self.assertEqual(second.bottom, 10)

        self.assertLessEqual(
            first.bottom,
            second.top,
        )

    def test_blank_candidate_mask_is_rejected(self):

        mask = np.zeros((10, 10), dtype=bool)

        candidates = self.make_candidates(mask)

        with self.assertRaises(ECGLeadSegmentationError):
            segment_ecg_lead_regions(candidates)

    @override_settings(
        ECG_LEAD_SEGMENTATION_MAX_GAP_ROWS=0,
        ECG_LEAD_SEGMENTATION_MAX_REGIONS=2,
    )
    def test_too_many_regions_are_rejected(self):

        mask = np.zeros((12, 8), dtype=bool)

        mask[1, 1:7] = True
        mask[5, 1:7] = True
        mask[9, 1:7] = True

        candidates = self.make_candidates(mask)

        with self.assertRaises(ECGLeadSegmentationError):
            segment_ecg_lead_regions(candidates)

    @override_settings(
        ECG_LEAD_SEGMENTATION_MIN_ACTIVE_PIXELS=3,
    )
    def test_rows_below_minimum_activity_are_ignored(self):

        mask = np.zeros((8, 8), dtype=bool)

        mask[1, 1] = True
        mask[5, 2:6] = True

        candidates = self.make_candidates(mask)

        result = segment_ecg_lead_regions(candidates)

        self.assertEqual(result.region_count, 1)

        self.assertEqual(
            result.regions[0].active_top,
            5,
        )

    def test_mismatched_dimensions_are_rejected(self):

        mask = np.zeros((6, 8), dtype=bool)

        candidates = ECGTraceCandidates(
            width=9,
            height=6,
            threshold=120,
            candidate_mask=mask,
            foreground_ratio=0.0,
            removed_dense_rows=0,
            removed_dense_columns=0,
        )

        with self.assertRaises(ECGLeadSegmentationError):
            segment_ecg_lead_regions(candidates)

    # =====================================================
    # ORIGINAL TESTS - Generic 2D Layout
    # =====================================================

    @override_settings(
        ECG_LEAD_SEGMENTATION_MAX_GAP_ROWS=0,
        ECG_LEAD_SEGMENTATION_PADDING_ROWS=0,
        ECG_LEAD_LAYOUT_MAX_GAP_COLUMNS=0,
        ECG_LEAD_LAYOUT_PADDING_COLUMNS=0,
    )
    def test_detects_three_by_four_ecg_layout(self):

        candidates = (
            self.make_three_by_four_layout_candidates()
        )

        result = segment_ecg_lead_layout(candidates)

        self.assertEqual(result.width, 23)
        self.assertEqual(result.height, 15)

        self.assertEqual(result.row_count, 3)
        self.assertEqual(result.cell_count, 12)

        self.assertEqual(
            result.columns_per_row,
            (4, 4, 4),
        )

        self.assertEqual(result.max_column_count, 4)

    @override_settings(
        ECG_LEAD_SEGMENTATION_MAX_GAP_ROWS=0,
        ECG_LEAD_SEGMENTATION_PADDING_ROWS=0,
        ECG_LEAD_LAYOUT_MAX_GAP_COLUMNS=0,
        ECG_LEAD_LAYOUT_PADDING_COLUMNS=0,
    )
    def test_layout_assigns_correct_row_and_column_indexes(self):

        candidates = (
            self.make_three_by_four_layout_candidates()
        )

        result = segment_ecg_lead_layout(candidates)

        expected_positions = (
            (1, 1),
            (1, 2),
            (1, 3),
            (1, 4),
            (2, 1),
            (2, 2),
            (2, 3),
            (2, 4),
            (3, 1),
            (3, 2),
            (3, 3),
            (3, 4),
        )

        actual_positions = tuple(
            (cell.row_index, cell.column_index)
            for cell in result.cells
        )

        self.assertEqual(
            actual_positions,
            expected_positions,
        )

        self.assertEqual(
            tuple(cell.index for cell in result.cells),
            tuple(range(1, 13)),
        )

    @override_settings(
        ECG_LEAD_SEGMENTATION_MAX_GAP_ROWS=0,
        ECG_LEAD_SEGMENTATION_PADDING_ROWS=0,
        ECG_LEAD_LAYOUT_MAX_GAP_COLUMNS=0,
        ECG_LEAD_LAYOUT_PADDING_COLUMNS=0,
    )
    def test_layout_cell_boundaries_match_detected_activity(self):

        candidates = (
            self.make_three_by_four_layout_candidates()
        )

        result = segment_ecg_lead_layout(candidates)

        first = result.cells[0]

        self.assertEqual(first.index, 1)
        self.assertEqual(first.row_index, 1)
        self.assertEqual(first.column_index, 1)

        self.assertEqual(
            (
                first.left,
                first.right,
                first.top,
                first.bottom,
            ),
            (1, 4, 1, 3),
        )

        self.assertEqual(
            (
                first.active_left,
                first.active_right,
                first.active_top,
                first.active_bottom,
            ),
            (1, 4, 1, 3),
        )

        self.assertEqual(first.width, 3)
        self.assertEqual(first.height, 2)

        self.assertEqual(first.active_width, 3)
        self.assertEqual(first.active_height, 2)

        self.assertEqual(first.candidate_pixel_count, 6)

    @override_settings(
        ECG_LEAD_SEGMENTATION_MAX_GAP_ROWS=0,
        ECG_LEAD_SEGMENTATION_PADDING_ROWS=0,
        ECG_LEAD_LAYOUT_MAX_GAP_COLUMNS=1,
        ECG_LEAD_LAYOUT_PADDING_COLUMNS=0,
    )
    def test_small_column_gap_is_grouped_into_one_layout_cell(self):

        mask = np.zeros((6, 10), dtype=bool)

        mask[2:4, 1:3] = True
        mask[2:4, 4:6] = True

        candidates = self.make_candidates(mask)

        result = segment_ecg_lead_layout(candidates)

        self.assertEqual(result.row_count, 1)
        self.assertEqual(result.cell_count, 1)

        cell = result.cells[0]

        self.assertEqual(cell.active_left, 1)
        self.assertEqual(cell.active_right, 6)

    @override_settings(
        ECG_LEAD_SEGMENTATION_MAX_GAP_ROWS=0,
        ECG_LEAD_SEGMENTATION_PADDING_ROWS=0,
        ECG_LEAD_LAYOUT_MAX_GAP_COLUMNS=0,
        ECG_LEAD_LAYOUT_PADDING_COLUMNS=2,
    )
    def test_layout_column_padding_does_not_create_overlap(self):

        mask = np.zeros((8, 12), dtype=bool)

        mask[3:5, 1:3] = True
        mask[3:5, 8:10] = True

        candidates = self.make_candidates(mask)

        result = segment_ecg_lead_layout(candidates)

        self.assertEqual(result.cell_count, 2)

        first = result.cells[0]
        second = result.cells[1]

        self.assertEqual(first.left, 0)
        self.assertEqual(second.right, 12)

        self.assertLessEqual(first.right, second.left)

    @override_settings(
        ECG_LEAD_SEGMENTATION_MAX_GAP_ROWS=0,
        ECG_LEAD_SEGMENTATION_PADDING_ROWS=0,
        ECG_LEAD_LAYOUT_MAX_GAP_COLUMNS=0,
        ECG_LEAD_LAYOUT_PADDING_COLUMNS=0,
        ECG_LEAD_LAYOUT_MAX_COLUMNS_PER_ROW=2,
    )
    def test_layout_rejects_too_many_columns_in_one_row(self):

        mask = np.zeros((6, 12), dtype=bool)

        mask[2:4, 1:3] = True
        mask[2:4, 5:7] = True
        mask[2:4, 9:11] = True

        candidates = self.make_candidates(mask)

        with self.assertRaises(ECGLeadSegmentationError):
            segment_ecg_lead_layout(candidates)

    @override_settings(
        ECG_LEAD_SEGMENTATION_MAX_GAP_ROWS=0,
        ECG_LEAD_SEGMENTATION_PADDING_ROWS=0,
        ECG_LEAD_LAYOUT_MAX_GAP_COLUMNS=0,
        ECG_LEAD_LAYOUT_PADDING_COLUMNS=0,
        ECG_LEAD_LAYOUT_MAX_CELLS=3,
    )
    def test_layout_rejects_too_many_total_cells(self):

        mask = np.zeros((10, 10), dtype=bool)

        mask[1:3, 1:3] = True
        mask[1:3, 6:8] = True
        mask[6:8, 1:3] = True
        mask[6:8, 6:8] = True

        candidates = self.make_candidates(mask)

        with self.assertRaises(ECGLeadSegmentationError):
            segment_ecg_lead_layout(candidates)

    @override_settings(
        ECG_LEAD_SEGMENTATION_MAX_GAP_ROWS=0,
        ECG_LEAD_SEGMENTATION_PADDING_ROWS=0,
        ECG_LEAD_LAYOUT_MIN_ACTIVE_PIXELS_PER_COLUMN=3,
    )
    def test_layout_rejects_row_without_sufficient_column_activity(
        self,
    ):

        mask = np.zeros((6, 8), dtype=bool)

        mask[2, 1:7] = True

        candidates = self.make_candidates(mask)

        with self.assertRaises(ECGLeadSegmentationError):
            segment_ecg_lead_layout(candidates)

    # =====================================================
    # NEW TESTS - Explicit Standard 3x4 Layout Profile
    # =====================================================

    def make_standard_3x4_profile_mask(
        self,
        *,
        row_ranges=((2, 8), (14, 20), (32, 38)),
        column_ranges=(
            (4, 24),
            (32, 52),
            (60, 80),
            (88, 108),
        ),
        shape=(44, 120),
    ):
        """
        Construct synthetic three-row, four-column ECG
        candidates independently of validation Case 001.
        """

        mask = np.zeros(shape, dtype=bool)

        for top, bottom in row_ranges:
            for left, right in column_ranges:
                mask[top:bottom, left:right] = True

        return mask

    # -----------------------------------------------------
    # TEST 16 - Expected Structure
    # -----------------------------------------------------

    def test_standard_3x4_profile_detects_expected_structure(self):

        candidates = self.make_candidates(
            self.make_standard_3x4_profile_mask()
        )

        result = segment_ecg_lead_layout(
            candidates,
            layout_profile="standard_3x4",
        )

        self.assertEqual(result.row_count, 3)
        self.assertEqual(result.cell_count, 12)

        self.assertEqual(
            result.columns_per_row,
            (4, 4, 4),
        )

        self.assertEqual(
            result.max_column_count,
            4,
        )

        self.assertEqual(
            tuple(
                (cell.row_index, cell.column_index)
                for cell in result.cells
            ),
            tuple(
                (row, column)
                for row in range(1, 4)
                for column in range(1, 5)
            ),
        )

        self.assertEqual(
            tuple(cell.index for cell in result.cells),
            tuple(range(1, 13)),
        )

    # -----------------------------------------------------
    # TEST 17 - Correct Non-Overlapping Cell Boundaries
    # -----------------------------------------------------

    def test_standard_3x4_profile_uses_nonoverlapping_boundaries(self):

        candidates = self.make_candidates(
            self.make_standard_3x4_profile_mask()
        )

        result = segment_ecg_lead_layout(
            candidates,
            layout_profile="standard_3x4",
        )

        expected_x = (4, 28, 56, 84, 108)
        expected_y = (0, 11, 26, 44)

        self.assertEqual(
            tuple(
                (row.top, row.bottom)
                for row in result.rows
            ),
            tuple(
                zip(expected_y, expected_y[1:])
            ),
        )

        for cell in result.cells:

            col = cell.column_index
            row = cell.row_index

            self.assertEqual(
                (
                    cell.left,
                    cell.top,
                    cell.right,
                    cell.bottom,
                ),
                (
                    expected_x[col - 1],
                    expected_y[row - 1],
                    expected_x[col],
                    expected_y[row],
                ),
            )

            self.assertGreater(
                cell.candidate_pixel_count,
                0,
            )

            self.assertGreater(cell.active_width, 0)
            self.assertGreater(cell.active_height, 0)

            self.assertLessEqual(
                cell.left,
                cell.active_left,
            )

            self.assertLessEqual(
                cell.active_right,
                cell.right,
            )

            self.assertLessEqual(
                cell.top,
                cell.active_top,
            )

            self.assertLessEqual(
                cell.active_bottom,
                cell.bottom,
            )

    # -----------------------------------------------------
    # TEST 18 - Ignore Small Extra Row
    # -----------------------------------------------------

    def test_standard_3x4_profile_ignores_a_small_extra_row(self):

        mask = self.make_standard_3x4_profile_mask()

        # Add one small disconnected strip.
        # It must not become a fourth dominant lead row.

        mask[24:25, 40:48] = True

        candidates = self.make_candidates(mask)

        self.assertEqual(
            segment_ecg_lead_regions(
                candidates
            ).region_count,
            4,
        )

        result = segment_ecg_lead_layout(
            candidates,
            layout_profile="standard_3x4",
        )

        self.assertEqual(result.row_count, 3)
        self.assertEqual(result.cell_count, 12)

        self.assertEqual(
            result.columns_per_row,
            (4, 4, 4),
        )

    # -----------------------------------------------------
    # TEST 19 - Reject Four Dominant Rows
    # -----------------------------------------------------

    def test_standard_3x4_profile_rejects_four_dominant_rows(self):

        mask = self.make_standard_3x4_profile_mask(
            row_ranges=(
                (2, 8),
                (14, 20),
                (26, 32),
                (38, 44),
            ),
            shape=(50, 120),
        )

        candidates = self.make_candidates(mask)

        with self.assertRaisesRegex(
            ECGLeadSegmentationError,
            "exactly three dominant signal rows",
        ):

            segment_ecg_lead_layout(
                candidates,
                layout_profile="standard_3x4",
            )

    # -----------------------------------------------------
    # TEST 20 - Reject Missing Main Row
    # -----------------------------------------------------

    def test_standard_3x4_profile_rejects_missing_main_row(self):

        mask = self.make_standard_3x4_profile_mask(
            row_ranges=(
                (2, 8),
                (14, 20),
            ),
        )

        candidates = self.make_candidates(mask)

        with self.assertRaisesRegex(
            ECGLeadSegmentationError,
            "requires three signal rows",
        ):

            segment_ecg_lead_layout(
                candidates,
                layout_profile="standard_3x4",
            )

    # -----------------------------------------------------
    # TEST 21 - Reject Missing Shared Gutters
    # -----------------------------------------------------

    def test_standard_3x4_profile_rejects_no_shared_gutters(self):

        mask = self.make_standard_3x4_profile_mask(
            column_ranges=(
                (4, 108),
            ),
        )

        candidates = self.make_candidates(mask)

        with self.assertRaisesRegex(
            ECGLeadSegmentationError,
            "shared vertical gutters",
        ):

            segment_ecg_lead_layout(
                candidates,
                layout_profile="standard_3x4",
            )

    # -----------------------------------------------------
    # TEST 22 - Reject Empty Signal Cell
    # -----------------------------------------------------

    def test_standard_3x4_profile_rejects_an_empty_cell(self):

        mask = self.make_standard_3x4_profile_mask()

        # Remove the fourth cell from the middle row.
        # Other rows still establish four column positions.

        mask[14:20, 88:108] = False

        candidates = self.make_candidates(mask)

        with self.assertRaisesRegex(
            ECGLeadSegmentationError,
            "empty signal cell",
        ):

            segment_ecg_lead_layout(
                candidates,
                layout_profile="standard_3x4",
            )

    # -----------------------------------------------------
    # TEST 23 - Reject Narrow Signal Extent
    # -----------------------------------------------------

    def test_standard_3x4_profile_rejects_narrow_signal_extent(self):

        mask = self.make_standard_3x4_profile_mask(
            column_ranges=(
                (5, 7),
            ),
        )

        candidates = self.make_candidates(mask)

        with self.assertRaisesRegex(
            ECGLeadSegmentationError,
            "too narrow",
        ):

            segment_ecg_lead_layout(
                candidates,
                layout_profile="standard_3x4",
            )

    # -----------------------------------------------------
    # TEST 24 - Reject Unknown Profile
    # -----------------------------------------------------

    def test_standard_3x4_profile_rejects_unknown_profile(self):

        candidates = (
            self.make_three_by_four_layout_candidates()
        )

        with self.assertRaisesRegex(
            ECGLeadSegmentationError,
            "Unsupported ECG lead layout profile",
        ):

            segment_ecg_lead_layout(
                candidates,
                layout_profile="standard_4x3",
            )

    # -----------------------------------------------------
    # TEST 25 - Preserve Generic Layout Behavior
    # -----------------------------------------------------

    def test_explicit_none_preserves_generic_layout_behavior(self):

        candidates = (
            self.make_three_by_four_layout_candidates()
        )

        default_result = segment_ecg_lead_layout(
            candidates
        )

        explicit_none_result = segment_ecg_lead_layout(
            candidates,
            layout_profile=None,
        )

        self.assertEqual(
            default_result,
            explicit_none_result,
        )
