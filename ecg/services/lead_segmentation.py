
"""
ECG Lead Segmentation Foundation.

Supports:
    - Vertical ECG lead-region segmentation.
    - Generic 2D ECG lead-layout segmentation.
    - Optional standard_3x4 real-image layout profile.

The optional standard_3x4 profile is intended for explicitly
confirmed three-row, four-column ECG printouts.

This module performs engineering-level image segmentation only.
It does not establish waveform accuracy or clinical validity.
"""

from dataclasses import dataclass

import numpy as np
from django.conf import settings

from ecg.services.trace_extraction import ECGTraceCandidates


# =========================================================
# Default Configuration
# =========================================================

DEFAULT_ECG_LEAD_SEGMENTATION_MIN_ACTIVE_PIXELS = 1
DEFAULT_ECG_LEAD_SEGMENTATION_MAX_GAP_ROWS = 2
DEFAULT_ECG_LEAD_SEGMENTATION_PADDING_ROWS = 2
DEFAULT_ECG_LEAD_SEGMENTATION_MAX_REGIONS = 16

DEFAULT_ECG_LEAD_LAYOUT_MIN_ACTIVE_PIXELS_PER_COLUMN = 1
DEFAULT_ECG_LEAD_LAYOUT_MAX_GAP_COLUMNS = 2
DEFAULT_ECG_LEAD_LAYOUT_PADDING_COLUMNS = 2
DEFAULT_ECG_LEAD_LAYOUT_MAX_COLUMNS_PER_ROW = 8
DEFAULT_ECG_LEAD_LAYOUT_MAX_CELLS = 24

# The following constants apply ONLY to the explicit standard_3x4 profile.
# A minimum of three agreeing horizontal probes allows one contaminated
# probe without deleting any source column from the final layout.
_STANDARD_3X4_PROBE_COUNT = 4
_STANDARD_3X4_MIN_VALID_PROBES = 3
_STANDARD_3X4_MIN_DOMINANT_COUNT_RATIO = 0.20
_STANDARD_3X4_MIN_DOMINANT_HEIGHT_RATIO = 0.40
_STANDARD_3X4_MAX_SEPARATOR_SPREAD_RATIO = 0.15


# =========================================================
# Exception
# =========================================================

class ECGLeadSegmentationError(ValueError):
    """Raised when ECG lead segmentation cannot complete safely."""


# =========================================================
# Vertical Lead Region
# =========================================================

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


# =========================================================
# 2D Lead Layout Cell
# =========================================================

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


# =========================================================
# 2D Lead Layout Result
# =========================================================

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

            counts.append(count)

        return tuple(counts)

    @property
    def max_column_count(self):
        if not self.cells:
            return 0

        return max(
            cell.column_index
            for cell in self.cells
        )


# =========================================================
# Candidate Validation
# =========================================================

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


# =========================================================
# Configuration Validation
# =========================================================

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


# =========================================================
# Grouping Helpers
# =========================================================

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

        position = int(position)

        gap = (
            position
            - previous
            - 1
        )

        if gap <= max_gap:
            previous = position
            continue

        groups.append(
            (start, previous)
        )

        start = position
        previous = position

    groups.append(
        (start, previous)
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


# =========================================================
# Boundary Helpers
# =========================================================

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
            [lower, upper]
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


# =========================================================
# Vertical Lead Region Segmentation
# =========================================================

def segment_ecg_lead_regions(candidates):

    mask = _validate_candidates(candidates)

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

    for index, (group, boundary) in enumerate(
        zip(groups, boundaries),
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
        regions=tuple(regions),
    )


# =========================================================
# Generic 2D Row Segmentation
# =========================================================

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
        column_counts >= min_active_pixels_per_column
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

    if len(column_groups) > max_columns_per_row:
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

    for column_index, (group, boundary) in enumerate(
        zip(column_groups, column_boundaries),
        start=1,
    ):

        active_left, active_right_inclusive = group
        left, right = boundary

        if right <= left:
            raise ECGLeadSegmentationError(
                "An invalid ECG lead-layout cell was produced."
            )

        active_right = active_right_inclusive + 1

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

    return tuple(cells)


# =========================================================
# Public 2D Layout Segmentation
# =========================================================

def segment_ecg_lead_layout(
    candidates,
    *,
    layout_profile=None,
):
    """
    Segment ECG candidates into a two-dimensional layout.

    Without layout_profile:
        Preserve the existing generic behavior.

    With layout_profile="standard_3x4":
        Use the optional three-row, four-column detection method.

    An explicit profile must only be selected when the source
    ECG printout has a confirmed compatible layout.
    """

    mask = _validate_candidates(candidates)

    # -----------------------------------------------------
    # Optional Explicit Layout Profile
    # -----------------------------------------------------

    if layout_profile is not None:

        if layout_profile == "standard_3x4":

            return _segment_explicit_standard_3x4(
                candidates,
                mask,
            )

        raise ECGLeadSegmentationError(
            "Unsupported ECG lead layout profile."
        )

    # -----------------------------------------------------
    # Existing Generic Segmentation
    # -----------------------------------------------------

    row_segmentation = segment_ecg_lead_regions(
        candidates
    )

    min_active_pixels_per_column = (
        _get_layout_min_active_pixels_per_column()
    )

    max_gap_columns = _get_layout_max_gap_columns()

    padding_columns = _get_layout_padding_columns()

    max_columns_per_row = (
        _get_layout_max_columns_per_row()
    )

    max_cells = _get_layout_max_cells()

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
            starting_cell_index=len(cells) + 1,
        )

        cells.extend(row_cells)

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
        cells=tuple(cells),
    )


# =========================================================
# Standard 3x4: Dominant Region Selection
# =========================================================

def _select_standard_3x4_dominant_regions(regions):
    """Apply the existing signal-size filter without forcing three rows."""

    if not regions:
        return ()

    largest_count = max(
        row.candidate_pixel_count
        for row in regions
    )

    largest_height = max(
        row.active_height
        for row in regions
    )

    if largest_count <= 0 or largest_height <= 0:
        return ()

    return tuple(
        row
        for row in regions
        if (
            row.candidate_pixel_count >= (
                _STANDARD_3X4_MIN_DOMINANT_COUNT_RATIO
                * largest_count
            )
            and row.active_height >= (
                _STANDARD_3X4_MIN_DOMINANT_HEIGHT_RATIO
                * largest_height
            )
        )
    )


# =========================================================
# Standard 3x4: Conservative Horizontal-Probe Fallback
# =========================================================

def _detect_standard_3x4_rows_from_probes(mask):
    """
    Estimate nominal row separators when full-width signals overlap.

    Divide the observed signal width into four horizontal probes.
    Each probe independently identifies its three dominant vertical bands.
    Require at least three successful probes and reasonably consistent
    separators. This tolerates one vertically contaminated probe.

    Only the row separators are inferred from the probes. The final
    cell detection still uses the original complete mask and all four
    columns; no source columns are deleted or muted.

    Returns three provisional full-width rows and four row boundaries.
    If consensus is unavailable, fail rather than force a 3x4 layout.
    """

    height, _ = mask.shape

    occupied_columns = np.flatnonzero(
        np.any(mask, axis=0)
    )

    if occupied_columns.size < 16:
        raise ECGLeadSegmentationError(
            "The standard_3x4 profile has insufficient horizontal "
            "signal extent for robust row detection."
        )

    left_edge = int(
        occupied_columns[0]
    )

    right_edge = (
        int(occupied_columns[-1]) + 1
    )

    signal_width = right_edge - left_edge

    if signal_width < 4 * 4:
        raise ECGLeadSegmentationError(
            "The standard_3x4 profile is too narrow for four row probes."
        )

    probe_edges = tuple(
        left_edge
        + (signal_width * index) // _STANDARD_3X4_PROBE_COUNT
        for index in range(_STANDARD_3X4_PROBE_COUNT + 1)
    )

    min_active_pixels = _get_min_active_pixels()
    max_gap_rows = _get_max_gap_rows()

    successful_separator_pairs = []

    for probe_left, probe_right in zip(
        probe_edges,
        probe_edges[1:],
    ):

        probe_mask = mask[
            :,
            probe_left:probe_right,
        ]

        if probe_mask.shape[1] < 4:
            continue

        row_counts = np.count_nonzero(
            probe_mask,
            axis=1,
        )

        active_rows = np.flatnonzero(
            row_counts >= min_active_pixels
        )

        if active_rows.size == 0:
            continue

        groups = _group_active_rows(
            active_rows,
            max_gap_rows,
        )

        probe_regions = tuple(
            ECGLeadRegion(
                index=index,
                top=int(start),
                bottom=int(end) + 1,
                active_top=int(start),
                active_bottom=int(end) + 1,
                candidate_pixel_count=int(
                    np.count_nonzero(
                        probe_mask[
                            start:end + 1,
                            :
                        ]
                    )
                ),
            )
            for index, (start, end) in enumerate(
                groups,
                start=1,
            )
        )

        dominant = _select_standard_3x4_dominant_regions(
            probe_regions
        )

        if len(dominant) != 3:
            continue

        first_separator = (
            dominant[0].active_bottom
            + dominant[1].active_top
        ) // 2

        second_separator = (
            dominant[1].active_bottom
            + dominant[2].active_top
        ) // 2

        if not (
            0
            < first_separator
            < second_separator
            < height
        ):
            continue

        successful_separator_pairs.append(
            (
                first_separator,
                second_separator,
            )
        )

    if (
        len(successful_separator_pairs)
        < _STANDARD_3X4_MIN_VALID_PROBES
    ):
        raise ECGLeadSegmentationError(
            "The standard_3x4 profile could not establish three "
            "signal rows from at least three horizontal probes."
        )

    separators = np.asarray(
        successful_separator_pairs,
        dtype=np.int64,
    )

    spread = np.ptp(
        separators,
        axis=0,
    )

    if np.any(
        spread
        > _STANDARD_3X4_MAX_SEPARATOR_SPREAD_RATIO * height
    ):
        raise ECGLeadSegmentationError(
            "The standard_3x4 profile found inconsistent row "
            "separators across horizontal probes."
        )

    # Median consensus resists one outlying, otherwise valid probe.
    first_separator, second_separator = (
        int(value)
        for value in np.rint(
            np.median(
                separators,
                axis=0,
            )
        )
    )

    row_boundaries = (
        0,
        first_separator,
        second_separator,
        height,
    )

    if any(
        bottom - top < max(
            2,
            int(0.10 * height),
        )
        for top, bottom in zip(
            row_boundaries,
            row_boundaries[1:],
        )
    ):
        raise ECGLeadSegmentationError(
            "The standard_3x4 profile produced implausible "
            "row heights from horizontal probes."
        )

    full_width_rows = []

    for index, (top, bottom) in enumerate(
        zip(
            row_boundaries,
            row_boundaries[1:],
        ),
        start=1,
    ):

        region_mask = mask[
            top:bottom,
            :
        ]

        active_local_rows = np.flatnonzero(
            np.any(
                region_mask,
                axis=1,
            )
        )

        if active_local_rows.size == 0:
            raise ECGLeadSegmentationError(
                "A consensus ECG row contains no trace candidates."
            )

        full_width_rows.append(
            ECGLeadRegion(
                index=index,
                top=int(top),
                bottom=int(bottom),
                active_top=int(
                    top + active_local_rows[0]
                ),
                active_bottom=int(
                    top + active_local_rows[-1] + 1
                ),
                candidate_pixel_count=int(
                    np.count_nonzero(region_mask)
                ),
            )
        )

    return (
        tuple(full_width_rows),
        row_boundaries,
    )


# =========================================================
# NEW: Opt-In Standard 3x4 Layout Profile
# =========================================================

def _segment_explicit_standard_3x4(candidates, mask):
    """
    Locate a 3-by-4 ECG grid using image evidence.

    Compared with the existing generic detector, this profile:

        1. Identifies three dominant signal bands.
        2. Excludes disconnected, small text-like regions.
        3. Searches for three shared vertical gutters.
        4. Produces twelve independent cell boundaries.

    The algorithm uses relative geometry and observed image gaps.
    It does not use the provisional validation annotations.

    Ambiguous layouts raise ECGLeadSegmentationError instead
    of silently forcing a 3x4 result.

    This is engineering segmentation, not clinical interpretation.
    """

    # -----------------------------------------------------
    # 1. Detect Existing Vertical Regions
    # -----------------------------------------------------

    generic_rows = segment_ecg_lead_regions(
        candidates
    ).regions

    # -----------------------------------------------------
    # 2. Select Three Dominant Signal Bands
    # -----------------------------------------------------

    main_rows = _select_standard_3x4_dominant_regions(
        generic_rows
    )

    row_boundaries = None

    if len(main_rows) != 3:

        if len(generic_rows) < 3:
            rejection_message = (
                "The standard_3x4 profile requires three signal rows."
            )
        else:
            rejection_message = (
                "The standard_3x4 profile could not establish "
                "exactly three dominant signal rows safely."
            )

        try:
            (
                main_rows,
                row_boundaries,
            ) = _detect_standard_3x4_rows_from_probes(
                mask
            )
        except ECGLeadSegmentationError as exc:
            raise ECGLeadSegmentationError(
                rejection_message
            ) from exc

    # -----------------------------------------------------
    # 3. Measure Combined Horizontal Signal Support
    # -----------------------------------------------------

    combined_column_counts = np.zeros(
        candidates.width,
        dtype=np.int64,
    )

    for row in main_rows:

        combined_column_counts += np.count_nonzero(
            mask[
                row.active_top:row.active_bottom,
                :
            ],
            axis=0,
        )

    nonempty_columns = np.flatnonzero(
        combined_column_counts > 0
    )

    if nonempty_columns.size == 0:
        raise ECGLeadSegmentationError(
            "No common horizontal ECG signal extent was found."
        )

    left_edge = int(
        nonempty_columns[0]
    )

    right_edge = (
        int(nonempty_columns[-1]) + 1
    )

    nominal_width = (
        right_edge - left_edge
    ) / 4.0

    if nominal_width < 4:
        raise ECGLeadSegmentationError(
            "The image is too narrow for the standard_3x4 profile."
        )

    # -----------------------------------------------------
    # 4. Detect Shared Blank Vertical Gutters
    # -----------------------------------------------------

    blank_positions = np.flatnonzero(
        combined_column_counts == 0
    )

    if blank_positions.size:

        blank_groups = _group_active_positions(
            blank_positions,
            0,
        )

    else:
        blank_groups = []

    interior_gutters = tuple(
        (
            int(start),
            int(end),
        )
        for start, end in blank_groups
        if (
            start > left_edge
            and end < right_edge - 1
            and end - start + 1 >= 2
        )
    )

    separator_positions = []

    used_gutters = set()

    # -----------------------------------------------------
    # 5. Identify the Three Column Separators
    # -----------------------------------------------------

    for separator_index in (1, 2, 3):

        approximate_position = (
            left_edge
            + separator_index * nominal_width
        )

        alternatives = []

        for gutter_index, (start, end) in enumerate(
            interior_gutters
        ):

            if gutter_index in used_gutters:
                continue

            center = (
                start + end + 1
            ) / 2.0

            distance = abs(
                center - approximate_position
            )

            if distance <= 0.30 * nominal_width:

                alternatives.append(
                    (
                        distance,
                        -(end - start + 1),
                        gutter_index,
                        int((start + end + 1) // 2),
                    )
                )

        if not alternatives:
            raise ECGLeadSegmentationError(
                "The standard_3x4 profile could not verify "
                "three shared vertical gutters safely."
            )

        (
            _,
            _,
            chosen_index,
            separator,
        ) = min(alternatives)

        used_gutters.add(
            chosen_index
        )

        separator_positions.append(
            separator
        )

    # -----------------------------------------------------
    # 6. Validate Four Column Boundaries
    # -----------------------------------------------------

    column_boundaries = (
        left_edge,
        *separator_positions,
        right_edge,
    )

    if any(
        right - left < 0.50 * nominal_width
        for left, right in zip(
            column_boundaries,
            column_boundaries[1:],
        )
    ):
        raise ECGLeadSegmentationError(
            "The standard_3x4 profile produced implausible "
            "cell widths."
        )

    # -----------------------------------------------------
    # 7. Establish Three Row Boundaries
    # -----------------------------------------------------

    if row_boundaries is None:

        row_separators = tuple(
            (
                current.active_bottom
                + following.active_top
            ) // 2
            for current, following in zip(
                main_rows,
                main_rows[1:],
            )
        )

        row_boundaries = (
            0,
            *row_separators,
            candidates.height,
        )

    rows = []
    cells = []

    # -----------------------------------------------------
    # 8. Construct Twelve Independent Layout Cells
    # -----------------------------------------------------

    for row_index, (
        original_row,
        top,
        bottom,
    ) in enumerate(
        zip(
            main_rows,
            row_boundaries,
            row_boundaries[1:],
        ),
        start=1,
    ):

        if not (
            top <= original_row.active_top
            < original_row.active_bottom <= bottom
        ):
            raise ECGLeadSegmentationError(
                "The standard_3x4 profile produced overlapping rows."
            )

        row = ECGLeadRegion(
            index=row_index,
            top=int(top),
            bottom=int(bottom),
            active_top=original_row.active_top,
            active_bottom=original_row.active_bottom,
            candidate_pixel_count=original_row.candidate_pixel_count,
        )

        rows.append(row)

        # -------------------------------------------------
        # Create Four Cells Inside the Current Row
        # -------------------------------------------------

        for column_index, (
            left,
            right,
        ) in enumerate(
            zip(
                column_boundaries,
                column_boundaries[1:],
            ),
            start=1,
        ):

            cell_mask = mask[
                row.active_top:row.active_bottom,
                left:right,
            ]

            count = int(
                np.count_nonzero(cell_mask)
            )

            if count <= 0:
                raise ECGLeadSegmentationError(
                    "The standard_3x4 profile contains an empty "
                    "signal cell."
                )

            active_local_columns = np.flatnonzero(
                np.any(
                    cell_mask,
                    axis=0,
                )
            )

            active_left = (
                int(left)
                + int(active_local_columns[0])
            )

            active_right = (
                int(left)
                + int(active_local_columns[-1])
                + 1
            )

            cells.append(
                ECGLeadLayoutCell(
                    index=len(cells) + 1,
                    row_index=row_index,
                    column_index=column_index,
                    left=int(left),
                    right=int(right),
                    top=row.top,
                    bottom=row.bottom,
                    active_left=active_left,
                    active_right=active_right,
                    active_top=row.active_top,
                    active_bottom=row.active_bottom,
                    candidate_pixel_count=count,
                )
            )

    # -----------------------------------------------------
    # 9. Final Structural Validation
    # -----------------------------------------------------

    if len(rows) != 3 or len(cells) != 12:
        raise ECGLeadSegmentationError(
            "The standard_3x4 profile could not produce "
            "twelve independent cell boundaries."
        )

    return ECGLeadLayoutResult(
        width=candidates.width,
        height=candidates.height,
        rows=tuple(rows),
        cells=tuple(cells),
    )
