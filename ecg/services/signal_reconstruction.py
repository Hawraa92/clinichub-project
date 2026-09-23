from dataclasses import dataclass

import numpy as np

from django.conf import settings

from ecg.services.trace_extraction import (
    ECGTraceCandidates,
)


DEFAULT_ECG_RECONSTRUCTION_MAX_GAP_COLUMNS = 12
DEFAULT_ECG_RECONSTRUCTION_MIN_COVERAGE = 0.25


class ECGSignalReconstructionError(ValueError):
    """Raised when an ECG trace cannot be reconstructed safely."""


@dataclass
class ReconstructedECGSignal:
    width: int
    height: int
    x_positions: tuple[int, ...]
    y_positions: tuple[float | None, ...]
    signal_values: tuple[float | None, ...]
    baseline_y: float
    coverage_ratio: float
    interpolated_columns: int
    region_top: int
    region_bottom: int

    @property
    def sample_count(self):
        return sum(
            value is not None
            for value in self.signal_values
        )

    @property
    def missing_count(self):
        return (
            self.width
            - self.sample_count
        )


def _validate_candidates(candidates):
    if not isinstance(
        candidates,
        ECGTraceCandidates,
    ):
        raise ECGSignalReconstructionError(
            "A valid ECGTraceCandidates instance is required."
        )

    candidate_mask = candidates.candidate_mask

    if not isinstance(
        candidate_mask,
        np.ndarray,
    ):
        raise ECGSignalReconstructionError(
            "The ECG trace candidates do not contain a valid mask."
        )

    if candidate_mask.ndim != 2:
        raise ECGSignalReconstructionError(
            "The ECG candidate mask must be two-dimensional."
        )

    if candidate_mask.size == 0:
        raise ECGSignalReconstructionError(
            "The ECG candidate mask is empty."
        )

    if (
        candidate_mask.shape[1]
        != candidates.width
        or candidate_mask.shape[0]
        != candidates.height
    ):
        raise ECGSignalReconstructionError(
            "The ECG candidate dimensions do not match the mask."
        )

    return np.asarray(
        candidate_mask,
        dtype=bool,
    )


def _validate_region(
    height,
    region_top,
    region_bottom,
):
    try:
        region_top = int(
            region_top
        )
    except (TypeError, ValueError) as exc:
        raise ECGSignalReconstructionError(
            "The ECG reconstruction region top must be an integer."
        ) from exc

    if region_bottom is None:
        region_bottom = height

    try:
        region_bottom = int(
            region_bottom
        )
    except (TypeError, ValueError) as exc:
        raise ECGSignalReconstructionError(
            "The ECG reconstruction region bottom must be an integer."
        ) from exc

    if region_top < 0:
        raise ECGSignalReconstructionError(
            "The ECG reconstruction region top cannot be negative."
        )

    if region_bottom > height:
        raise ECGSignalReconstructionError(
            "The ECG reconstruction region exceeds the image height."
        )

    if region_bottom <= region_top:
        raise ECGSignalReconstructionError(
            "The ECG reconstruction region is invalid."
        )

    return (
        region_top,
        region_bottom,
    )


def _get_max_gap_columns():
    value = getattr(
        settings,
        "ECG_RECONSTRUCTION_MAX_GAP_COLUMNS",
        DEFAULT_ECG_RECONSTRUCTION_MAX_GAP_COLUMNS,
    )

    try:
        value = int(
            value
        )
    except (TypeError, ValueError) as exc:
        raise ECGSignalReconstructionError(
            "The ECG reconstruction gap limit must be an integer."
        ) from exc

    if value < 0:
        raise ECGSignalReconstructionError(
            "The ECG reconstruction gap limit cannot be negative."
        )

    return value


def _get_min_coverage():
    value = getattr(
        settings,
        "ECG_RECONSTRUCTION_MIN_COVERAGE",
        DEFAULT_ECG_RECONSTRUCTION_MIN_COVERAGE,
    )

    try:
        value = float(
            value
        )
    except (TypeError, ValueError) as exc:
        raise ECGSignalReconstructionError(
            "The ECG reconstruction coverage limit must be numeric."
        ) from exc

    if value <= 0 or value > 1:
        raise ECGSignalReconstructionError(
            "The ECG reconstruction coverage limit must be "
            "greater than 0 and no greater than 1."
        )

    return value


def _choose_column_position(
    rows,
    previous_y,
):
    if rows.size == 0:
        return None

    if previous_y is None:
        return float(
            np.median(
                rows
            )
        )

    distances = np.abs(
        rows.astype(
            np.float64
        )
        - previous_y
    )

    nearest_distance = np.min(
        distances
    )

    nearest_rows = rows[
        distances == nearest_distance
    ]

    return float(
        np.median(
            nearest_rows
        )
    )


def _extract_column_path(
    candidate_mask,
    region_top,
    region_bottom,
):
    width = candidate_mask.shape[1]

    positions = [
        None
    ] * width

    previous_y = None

    for column_index in range(
        width
    ):
        rows = np.flatnonzero(
            candidate_mask[
                region_top:region_bottom,
                column_index,
            ]
        )

        if rows.size == 0:
            continue

        rows = (
            rows
            + region_top
        )

        selected_y = _choose_column_position(
            rows,
            previous_y,
        )

        positions[
            column_index
        ] = selected_y

        previous_y = selected_y

    return positions


def _interpolate_short_gaps(
    positions,
    max_gap_columns,
):
    interpolated = list(
        positions
    )

    interpolated_columns = 0

    index = 0
    width = len(
        interpolated
    )

    while index < width:
        if interpolated[index] is not None:
            index += 1
            continue

        gap_start = index

        while (
            index < width
            and interpolated[index] is None
        ):
            index += 1

        gap_end = index

        gap_length = (
            gap_end
            - gap_start
        )

        left_index = (
            gap_start
            - 1
        )

        right_index = gap_end

        if (
            gap_length == 0
            or gap_length > max_gap_columns
            or left_index < 0
            or right_index >= width
        ):
            continue

        left_value = interpolated[
            left_index
        ]

        right_value = interpolated[
            right_index
        ]

        if (
            left_value is None
            or right_value is None
        ):
            continue

        step = (
            right_value
            - left_value
        ) / (
            gap_length
            + 1
        )

        for gap_offset in range(
            1,
            gap_length + 1,
        ):
            interpolated[
                left_index
                + gap_offset
            ] = (
                left_value
                + step
                * gap_offset
            )

            interpolated_columns += 1

    return (
        interpolated,
        interpolated_columns,
    )


def _calculate_coverage(
    positions,
):
    if not positions:
        return 0.0

    available_count = sum(
        value is not None
        for value in positions
    )

    return (
        available_count
        / len(
            positions
        )
    )


def _calculate_baseline(
    positions,
):
    valid_positions = [
        value
        for value in positions
        if value is not None
    ]

    if not valid_positions:
        raise ECGSignalReconstructionError(
            "No ECG signal positions were reconstructed."
        )

    return float(
        np.median(
            np.asarray(
                valid_positions,
                dtype=np.float64,
            )
        )
    )


def _build_signal_values(
    positions,
    baseline_y,
):
    signal_values = []

    for y_position in positions:
        if y_position is None:
            signal_values.append(
                None
            )
            continue

        signal_values.append(
            float(
                baseline_y
                - y_position
            )
        )

    return signal_values


def reconstruct_ecg_signal(
    candidates,
    region_top=0,
    region_bottom=None,
):
    candidate_mask = _validate_candidates(
        candidates
    )

    (
        region_top,
        region_bottom,
    ) = _validate_region(
        candidates.height,
        region_top,
        region_bottom,
    )

    max_gap_columns = (
        _get_max_gap_columns()
    )

    min_coverage = (
        _get_min_coverage()
    )

    positions = _extract_column_path(
        candidate_mask,
        region_top,
        region_bottom,
    )

    raw_coverage = _calculate_coverage(
        positions
    )

    if raw_coverage < min_coverage:
        raise ECGSignalReconstructionError(
            "The ECG trace does not cover enough of the image "
            "to reconstruct a reliable signal path."
        )

    (
        positions,
        interpolated_columns,
    ) = _interpolate_short_gaps(
        positions,
        max_gap_columns,
    )

    final_coverage = _calculate_coverage(
        positions
    )

    baseline_y = _calculate_baseline(
        positions
    )

    signal_values = _build_signal_values(
        positions,
        baseline_y,
    )

    return ReconstructedECGSignal(
        width=candidates.width,
        height=candidates.height,
        x_positions=tuple(
            range(
                candidates.width
            )
        ),
        y_positions=tuple(
            positions
        ),
        signal_values=tuple(
            signal_values
        ),
        baseline_y=baseline_y,
        coverage_ratio=final_coverage,
        interpolated_columns=interpolated_columns,
        region_top=region_top,
        region_bottom=region_bottom,
    )