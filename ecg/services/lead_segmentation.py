from dataclasses import dataclass

import numpy as np
from django.conf import settings

from ecg.services.trace_extraction import ECGTraceCandidates


DEFAULT_ECG_LEAD_SEGMENTATION_MIN_ACTIVE_PIXELS = 1
DEFAULT_ECG_LEAD_SEGMENTATION_MAX_GAP_ROWS = 2
DEFAULT_ECG_LEAD_SEGMENTATION_PADDING_ROWS = 2
DEFAULT_ECG_LEAD_SEGMENTATION_MAX_REGIONS = 16


class ECGLeadSegmentationError(ValueError):
    """Raised when ECG lead-region segmentation cannot be completed safely."""


@dataclass(frozen=True)
class ECGLeadRegion:
    index: int
    top: int
    bottom: int
    active_top: int
    active_bottom: int
    candidate_pixel_count: int

    @property
    def height(self):
        return self.bottom - self.top

    @property
    def active_height(self):
        return self.active_bottom - self.active_top


@dataclass(frozen=True)
class ECGLeadSegmentationResult:
    width: int
    height: int
    regions: tuple[ECGLeadRegion, ...]

    @property
    def region_count(self):
        return len(self.regions)


def _validate_candidates(candidates):
    if not isinstance(
        candidates,
        ECGTraceCandidates,
    ):
        raise ECGLeadSegmentationError(
            "Expected ECGTraceCandidates."
        )

    mask = candidates.candidate_mask

    if not isinstance(mask, np.ndarray):
        raise ECGLeadSegmentationError(
            "Candidate mask must be a NumPy array."
        )

    if mask.ndim != 2:
        raise ECGLeadSegmentationError(
            "Candidate mask must be two-dimensional."
        )

    if mask.size == 0:
        raise ECGLeadSegmentationError(
            "Candidate mask cannot be empty."
        )

    height, width = mask.shape

    if (
        width != candidates.width
        or height != candidates.height
    ):
        raise ECGLeadSegmentationError(
            "Candidate mask dimensions do not match metadata."
        )

    return mask.astype(
        bool,
        copy=False,
    )


def _get_min_active_pixels():
    value = getattr(
        settings,
        "ECG_LEAD_SEGMENTATION_MIN_ACTIVE_PIXELS",
        DEFAULT_ECG_LEAD_SEGMENTATION_MIN_ACTIVE_PIXELS,
    )

    if (
        not isinstance(value, int)
        or isinstance(value, bool)
        or value < 1
    ):
        raise ECGLeadSegmentationError(
            "Minimum active pixels must be a positive integer."
        )

    return value


def _get_max_gap_rows():
    value = getattr(
        settings,
        "ECG_LEAD_SEGMENTATION_MAX_GAP_ROWS",
        DEFAULT_ECG_LEAD_SEGMENTATION_MAX_GAP_ROWS,
    )

    if (
        not isinstance(value, int)
        or isinstance(value, bool)
        or value < 0
    ):
        raise ECGLeadSegmentationError(
            "Maximum gap rows must be a non-negative integer."
        )

    return value


def _get_padding_rows():
    value = getattr(
        settings,
        "ECG_LEAD_SEGMENTATION_PADDING_ROWS",
        DEFAULT_ECG_LEAD_SEGMENTATION_PADDING_ROWS,
    )

    if (
        not isinstance(value, int)
        or isinstance(value, bool)
        or value < 0
    ):
        raise ECGLeadSegmentationError(
            "Padding rows must be a non-negative integer."
        )

    return value


def _get_max_regions():
    value = getattr(
        settings,
        "ECG_LEAD_SEGMENTATION_MAX_REGIONS",
        DEFAULT_ECG_LEAD_SEGMENTATION_MAX_REGIONS,
    )

    if (
        not isinstance(value, int)
        or isinstance(value, bool)
        or value < 1
    ):
        raise ECGLeadSegmentationError(
            "Maximum region count must be a positive integer."
        )

    return value


def _group_active_rows(
    active_rows,
    max_gap_rows,
):
    groups = []

    start = int(
        active_rows[0]
    )
    previous = start

    for row in active_rows[1:]:
        row = int(row)

        gap = row - previous - 1

        if gap <= max_gap_rows:
            previous = row
            continue

        groups.append(
            (
                start,
                previous,
            )
        )

        start = row
        previous = row

    groups.append(
        (
            start,
            previous,
        )
    )

    return groups


def _build_region_boundaries(
    groups,
    height,
    padding_rows,
):
    boundaries = []

    for start, end in groups:
        top = max(
            0,
            start - padding_rows,
        )

        bottom = min(
            height,
            end + padding_rows + 1,
        )

        boundaries.append(
            [
                top,
                bottom,
            ]
        )

    for index in range(
        len(boundaries) - 1
    ):
        current = boundaries[index]
        following = boundaries[index + 1]

        if current[1] <= following[0]:
            continue

        current_active_end = groups[index][1]
        next_active_start = groups[index + 1][0]

        separator = (
            current_active_end
            + next_active_start
            + 1
        ) // 2

        current[1] = separator
        following[0] = separator

    return boundaries


def segment_ecg_lead_regions(
    candidates,
):
    mask = _validate_candidates(
        candidates
    )

    min_active_pixels = _get_min_active_pixels()
    max_gap_rows = _get_max_gap_rows()
    padding_rows = _get_padding_rows()
    max_regions = _get_max_regions()

    row_counts = np.count_nonzero(
        mask,
        axis=1,
    )

    active_rows = np.flatnonzero(
        row_counts >= min_active_pixels
    )

    if active_rows.size == 0:
        raise ECGLeadSegmentationError(
            "No active ECG trace rows were detected."
        )

    groups = _group_active_rows(
        active_rows,
        max_gap_rows,
    )

    if len(groups) > max_regions:
        raise ECGLeadSegmentationError(
            "Too many possible ECG lead regions were detected."
        )

    boundaries = _build_region_boundaries(
        groups,
        candidates.height,
        padding_rows,
    )

    regions = []

    for index, (
        group,
        boundary,
    ) in enumerate(
        zip(
            groups,
            boundaries,
        ),
        start=1,
    ):
        active_start, active_end = group
        top, bottom = boundary

        if bottom <= top:
            raise ECGLeadSegmentationError(
                "An invalid ECG lead region was produced."
            )

        candidate_pixel_count = int(
            np.count_nonzero(
                mask[
                    active_start:active_end + 1,
                    :
                ]
            )
        )

        if candidate_pixel_count <= 0:
            raise ECGLeadSegmentationError(
                "An ECG lead region contains no trace candidates."
            )

        regions.append(
            ECGLeadRegion(
                index=index,
                top=top,
                bottom=bottom,
                active_top=active_start,
                active_bottom=active_end + 1,
                candidate_pixel_count=candidate_pixel_count,
            )
        )

    return ECGLeadSegmentationResult(
        width=candidates.width,
        height=candidates.height,
        regions=tuple(
            regions
        ),
    )