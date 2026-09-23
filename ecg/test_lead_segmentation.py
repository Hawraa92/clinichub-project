import numpy as np

from django.test import SimpleTestCase, override_settings

from ecg.services.lead_segmentation import (
    ECGLeadSegmentationError,
    segment_ecg_lead_regions,
)
from ecg.services.trace_extraction import ECGTraceCandidates


class ECGLeadSegmentationTests(SimpleTestCase):
    def make_candidates(
        self,
        mask,
    ):
        mask = np.asarray(
            mask,
            dtype=bool,
        )

        height, width = mask.shape

        candidate_pixel_count = int(
            np.count_nonzero(mask)
        )

        foreground_ratio = (
            candidate_pixel_count
            / mask.size
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

    @override_settings(
        ECG_LEAD_SEGMENTATION_MAX_GAP_ROWS=0,
        ECG_LEAD_SEGMENTATION_PADDING_ROWS=0,
    )
    def test_separates_distinct_vertical_regions(self):
        mask = np.zeros(
            (
                12,
                10,
            ),
            dtype=bool,
        )

        mask[1:3, 1:9] = True
        mask[7:9, 1:9] = True

        candidates = self.make_candidates(
            mask
        )

        result = segment_ecg_lead_regions(
            candidates
        )

        self.assertEqual(
            result.region_count,
            2,
        )

        first = result.regions[0]
        second = result.regions[1]

        self.assertEqual(
            (
                first.top,
                first.bottom,
            ),
            (
                1,
                3,
            ),
        )

        self.assertEqual(
            (
                second.top,
                second.bottom,
            ),
            (
                7,
                9,
            ),
        )

    @override_settings(
        ECG_LEAD_SEGMENTATION_MAX_GAP_ROWS=1,
        ECG_LEAD_SEGMENTATION_PADDING_ROWS=0,
    )
    def test_small_row_gap_is_grouped_into_one_region(self):
        mask = np.zeros(
            (
                10,
                8,
            ),
            dtype=bool,
        )

        mask[2, 1:7] = True
        mask[4, 1:7] = True

        candidates = self.make_candidates(
            mask
        )

        result = segment_ecg_lead_regions(
            candidates
        )

        self.assertEqual(
            result.region_count,
            1,
        )

        region = result.regions[0]

        self.assertEqual(
            region.active_top,
            2,
        )

        self.assertEqual(
            region.active_bottom,
            5,
        )

    @override_settings(
        ECG_LEAD_SEGMENTATION_MAX_GAP_ROWS=0,
        ECG_LEAD_SEGMENTATION_PADDING_ROWS=2,
    )
    def test_padding_is_applied_without_exceeding_image(self):
        mask = np.zeros(
            (
                10,
                8,
            ),
            dtype=bool,
        )

        mask[1, 1:7] = True
        mask[8, 1:7] = True

        candidates = self.make_candidates(
            mask
        )

        result = segment_ecg_lead_regions(
            candidates
        )

        first = result.regions[0]
        second = result.regions[1]

        self.assertEqual(
            first.top,
            0,
        )

        self.assertEqual(
            second.bottom,
            10,
        )

        self.assertLessEqual(
            first.bottom,
            second.top,
        )

    def test_blank_candidate_mask_is_rejected(self):
        mask = np.zeros(
            (
                10,
                10,
            ),
            dtype=bool,
        )

        candidates = self.make_candidates(
            mask
        )

        with self.assertRaises(
            ECGLeadSegmentationError
        ):
            segment_ecg_lead_regions(
                candidates
            )

    @override_settings(
        ECG_LEAD_SEGMENTATION_MAX_GAP_ROWS=0,
        ECG_LEAD_SEGMENTATION_MAX_REGIONS=2,
    )
    def test_too_many_regions_are_rejected(self):
        mask = np.zeros(
            (
                12,
                8,
            ),
            dtype=bool,
        )

        mask[1, 1:7] = True
        mask[5, 1:7] = True
        mask[9, 1:7] = True

        candidates = self.make_candidates(
            mask
        )

        with self.assertRaises(
            ECGLeadSegmentationError
        ):
            segment_ecg_lead_regions(
                candidates
            )

    @override_settings(
        ECG_LEAD_SEGMENTATION_MIN_ACTIVE_PIXELS=3,
    )
    def test_rows_below_minimum_activity_are_ignored(self):
        mask = np.zeros(
            (
                8,
                8,
            ),
            dtype=bool,
        )

        mask[1, 1] = True
        mask[5, 2:6] = True

        candidates = self.make_candidates(
            mask
        )

        result = segment_ecg_lead_regions(
            candidates
        )

        self.assertEqual(
            result.region_count,
            1,
        )

        self.assertEqual(
            result.regions[0].active_top,
            5,
        )

    def test_mismatched_dimensions_are_rejected(self):
        mask = np.zeros(
            (
                6,
                8,
            ),
            dtype=bool,
        )

        candidates = ECGTraceCandidates(
            width=9,
            height=6,
            threshold=120,
            candidate_mask=mask,
            foreground_ratio=0.0,
            removed_dense_rows=0,
            removed_dense_columns=0,
        )

        with self.assertRaises(
            ECGLeadSegmentationError
        ):
            segment_ecg_lead_regions(
                candidates
            )