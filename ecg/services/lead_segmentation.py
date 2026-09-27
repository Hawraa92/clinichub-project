from dataclasses import dataclass

import numpy as np
from django.conf import settings

from ecg.services.trace_extraction import ECGTraceCandidates


DEFAULT_ECG_LEAD_SEGMENTATION_MIN_ACTIVE_PIXELS = 1
DEFAULT_ECG_LEAD_SEGMENTATION_MAX_GAP_ROWS = 2
DEFAULT_ECG_LEAD_SEGMENTATION_PADDING_ROWS = 2
DEFAULT_ECG_LEAD_SEGMENTATION_MAX_REGIONS = 16

DEFAULT_ECG_LEAD_LAYOUT_MIN_ACTIVE_PIXELS_PER_COLUMN = 1
DEFAULT_ECG_LEAD_LAYOUT_MAX_GAP_COLUMNS = 2
DEFAULT_ECG_LEAD_LAYOUT_PADDING_COLUMNS = 2
DEFAULT_ECG_LEAD_LAYOUT_MAX_COLUMNS_PER_ROW = 8
DEFAULT_ECG_LEAD_LAYOUT_MAX_CELLS = 24


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


@dataclass(frozen=True)
class ECGLeadLayoutCell:
    index: int
    row_index: int
    column_index: int
    left: int
    right: int
    top: int
    bottom: int
    active_left: int
    active_right: int
    active_top: int
    active_bottom: int
    candidate_pixel_count: int

    @property
    def width(self):
        return self.right - self.left

    @property
    def height(self):
        return self.bottom - self.top

    @property
    def active_width(self):
        return self.active_right - self.active_left

    @property
    def active_height(self):
        return self.active_bottom - self.active_top


@dataclass(frozen=True)
class ECGLeadLayoutResult:
    width: int
    height: int
    rows: tuple[ECGLeadRegion, ...]
    cells: tuple[ECGLeadLayoutCell, ...]

    @property
    def row_count(self):
        return len(self.rows)

    @property
    def cell_count(self):
        return len(self.cells)

    @property
    def columns_per_row(self):
        counts = []

        for row in self.rows:
            count = sum(
                1
                for cell in self.cells
                if cell.row_index == row.index
            )

            counts.append(
                count
            )

        return tuple(
            counts
        )

    @property
    def max_column_count(self):
        if not self.cells:
            return 0

        return max(
            cell.column_index
            for cell in self.cells
        )


def _validate_candidates(candidates):
    if not isinstance(
        candidates,
        ECGTraceCandidates,
    ):
        raise ECGLeadSegmentationError(
            "Expected ECGTraceCandidates."
        )

    mask = candidates.candidate_mask

    if not isinstance(
        mask,
        np.ndarray,
    ):
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


def _get_layout_min_active_pixels_per_column():
    value = getattr(
        settings,
        "ECG_LEAD_LAYOUT_MIN_ACTIVE_PIXELS_PER_COLUMN",
        DEFAULT_ECG_LEAD_LAYOUT_MIN_ACTIVE_PIXELS_PER_COLUMN,
    )

    if (
        not isinstance(value, int)
        or isinstance(value, bool)
        or value < 1
    ):
        raise ECGLeadSegmentationError(
            "Minimum active pixels per layout column "
            "must be a positive integer."
        )

    return value


def _get_layout_max_gap_columns():
    value = getattr(
        settings,
        "ECG_LEAD_LAYOUT_MAX_GAP_COLUMNS",
        DEFAULT_ECG_LEAD_LAYOUT_MAX_GAP_COLUMNS,
    )

    if (
        not isinstance(value, int)
        or isinstance(value, bool)
        or value < 0
    ):
        raise ECGLeadSegmentationError(
            "Maximum layout column gap must be "
            "a non-negative integer."
        )

    return value


def _get_layout_padding_columns():
    value = getattr(
        settings,
        "ECG_LEAD_LAYOUT_PADDING_COLUMNS",
        DEFAULT_ECG_LEAD_LAYOUT_PADDING_COLUMNS,
    )

    if (
        not isinstance(value, int)
        or isinstance(value, bool)
        or value < 0
    ):
        raise ECGLeadSegmentationError(
            "Layout column padding must be "
            "a non-negative integer."
        )

    return value


def _get_layout_max_columns_per_row():
    value = getattr(
        settings,
        "ECG_LEAD_LAYOUT_MAX_COLUMNS_PER_ROW",
        DEFAULT_ECG_LEAD_LAYOUT_MAX_COLUMNS_PER_ROW,
    )

    if (
        not isinstance(value, int)
        or isinstance(value, bool)
        or value < 1
    ):
        raise ECGLeadSegmentationError(
            "Maximum layout columns per row "
            "must be a positive integer."
        )

    return value


def _get_layout_max_cells():
    value = getattr(
        settings,
        "ECG_LEAD_LAYOUT_MAX_CELLS",
        DEFAULT_ECG_LEAD_LAYOUT_MAX_CELLS,
    )

    if (
        not isinstance(value, int)
        or isinstance(value, bool)
        or value < 1
    ):
        raise ECGLeadSegmentationError(
            "Maximum ECG lead-layout cell count "
            "must be a positive integer."
        )

    return value


def _group_active_positions(
    active_positions,
    max_gap,
):
    groups = []

    start = int(
        active_positions[0]
    )

    previous = start

    for position in active_positions[1:]:
        position = int(
            position
        )

        gap = (
            position
            - previous
            - 1
        )

        if gap <= max_gap:
            previous = position
            continue

        groups.append(
            (
                start,
                previous,
            )
        )

        start = position
        previous = position

    groups.append(
        (
            start,
            previous,
        )
    )

    return groups


def _group_active_rows(
    active_rows,
    max_gap_rows,
):
    return _group_active_positions(
        active_rows,
        max_gap_rows,
    )


def _group_active_columns(
    active_columns,
    max_gap_columns,
):
    return _group_active_positions(
        active_columns,
        max_gap_columns,
    )


def _build_boundaries(
    groups,
    dimension_size,
    padding,
):
    boundaries = []

    for start, end in groups:
        lower = max(
            0,
            start - padding,
        )

        upper = min(
            dimension_size,
            end + padding + 1,
        )

        boundaries.append(
            [
                lower,
                upper,
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


def _build_region_boundaries(
    groups,
    height,
    padding_rows,
):
    return _build_boundaries(
        groups,
        height,
        padding_rows,
    )


def _build_column_boundaries(
    groups,
    width,
    padding_columns,
):
    return _build_boundaries(
        groups,
        width,
        padding_columns,
    )


def segment_ecg_lead_regions(
    candidates,
):
    mask = _validate_candidates(
        candidates
    )

    min_active_pixels = (
        _get_min_active_pixels()
    )

    max_gap_rows = (
        _get_max_gap_rows()
    )

    padding_rows = (
        _get_padding_rows()
    )

    max_regions = (
        _get_max_regions()
    )

    row_counts = np.count_nonzero(
        mask,
        axis=1,
    )

    active_rows = np.flatnonzero(
        row_counts
        >= min_active_pixels
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


def _segment_layout_row(
    mask,
    row,
    *,
    width,
    min_active_pixels_per_column,
    max_gap_columns,
    padding_columns,
    max_columns_per_row,
    starting_cell_index,
):
    row_mask = mask[
        row.active_top:row.active_bottom,
        :
    ]

    column_counts = np.count_nonzero(
        row_mask,
        axis=0,
    )

    active_columns = np.flatnonzero(
        column_counts
        >= min_active_pixels_per_column
    )

    if active_columns.size == 0:
        raise ECGLeadSegmentationError(
            f"No active ECG trace columns were detected "
            f"for row {row.index}."
        )

    column_groups = _group_active_columns(
        active_columns,
        max_gap_columns,
    )

    if len(
        column_groups
    ) > max_columns_per_row:
        raise ECGLeadSegmentationError(
            f"Too many possible ECG lead columns were "
            f"detected for row {row.index}."
        )

    column_boundaries = _build_column_boundaries(
        column_groups,
        width,
        padding_columns,
    )

    cells = []

    for column_index, (
        group,
        boundary,
    ) in enumerate(
        zip(
            column_groups,
            column_boundaries,
        ),
        start=1,
    ):
        (
            active_left,
            active_right_inclusive,
        ) = group

        left, right = boundary

        if right <= left:
            raise ECGLeadSegmentationError(
                "An invalid ECG lead-layout cell was produced."
            )

        active_right = (
            active_right_inclusive
            + 1
        )

        candidate_pixel_count = int(
            np.count_nonzero(
                mask[
                    row.active_top:row.active_bottom,
                    active_left:active_right,
                ]
            )
        )

        if candidate_pixel_count <= 0:
            raise ECGLeadSegmentationError(
                "An ECG lead-layout cell contains "
                "no trace candidates."
            )

        cell_index = (
            starting_cell_index
            + len(cells)
        )

        cells.append(
            ECGLeadLayoutCell(
                index=cell_index,
                row_index=row.index,
                column_index=column_index,
                left=left,
                right=right,
                top=row.top,
                bottom=row.bottom,
                active_left=active_left,
                active_right=active_right,
                active_top=row.active_top,
                active_bottom=row.active_bottom,
                candidate_pixel_count=candidate_pixel_count,
            )
        )

    return tuple(
        cells
    )


def segment_ecg_lead_layout(
    candidates,
):
    mask = _validate_candidates(
        candidates
    )

    row_segmentation = (
        segment_ecg_lead_regions(
            candidates
        )
    )

    min_active_pixels_per_column = (
        _get_layout_min_active_pixels_per_column()
    )

    max_gap_columns = (
        _get_layout_max_gap_columns()
    )

    padding_columns = (
        _get_layout_padding_columns()
    )

    max_columns_per_row = (
        _get_layout_max_columns_per_row()
    )

    max_cells = (
        _get_layout_max_cells()
    )

    cells = []

    for row in row_segmentation.regions:
        row_cells = _segment_layout_row(
            mask,
            row,
            width=candidates.width,
            min_active_pixels_per_column=(
                min_active_pixels_per_column
            ),
            max_gap_columns=max_gap_columns,
            padding_columns=padding_columns,
            max_columns_per_row=(
                max_columns_per_row
            ),
            starting_cell_index=(
                len(cells)
                + 1
            ),
        )

        cells.extend(
            row_cells
        )

        if len(cells) > max_cells:
            raise ECGLeadSegmentationError(
                "Too many possible ECG lead-layout "
                "cells were detected."
            )

    if not cells:
        raise ECGLeadSegmentationError(
            "No ECG lead-layout cells were detected."
        )

    return ECGLeadLayoutResult(
        width=candidates.width,
        height=candidates.height,
        rows=row_segmentation.regions,
        cells=tuple(
            cells
        ),
    )