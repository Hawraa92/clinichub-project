from dataclasses import dataclass
import math

import numpy as np

from ecg.services.image_processing import (
    ProcessedECGImage,
)


DEFAULT_ECG_GRID_MIN_CONTRAST = 8.0
DEFAULT_ECG_GRID_PEAK_RATIO = 0.20
DEFAULT_ECG_GRID_MIN_LINE_COUNT = 4
DEFAULT_ECG_GRID_MIN_SPACING_PIXELS = 2.0
DEFAULT_ECG_GRID_AXIS_TOLERANCE_RATIO = 0.20
DEFAULT_ECG_GRID_INTERVAL_TOLERANCE_RATIO = 0.25


class ECGGridDetectionError(ValueError):
    """Raised when ECG grid scale cannot be detected safely."""


@dataclass(frozen=True)
class ECGGridDetectionResult:
    pixels_per_mm: float
    x_spacing_pixels: float
    y_spacing_pixels: float
    x_grid_line_positions: tuple[float, ...]
    y_grid_line_positions: tuple[float, ...]
    axis_difference_ratio: float

    @property
    def x_line_count(self):
        return len(
            self.x_grid_line_positions
        )

    @property
    def y_line_count(self):
        return len(
            self.y_grid_line_positions
        )

    @property
    def x_interval_count(self):
        return max(
            0,
            self.x_line_count - 1,
        )

    @property
    def y_interval_count(self):
        return max(
            0,
            self.y_line_count - 1,
        )


def _validate_processed_image(
    processed_image,
):
    if not isinstance(
        processed_image,
        ProcessedECGImage,
    ):
        raise ECGGridDetectionError(
            "Expected ProcessedECGImage."
        )

    grayscale = np.asarray(
        processed_image.grayscale
    )

    if grayscale.ndim != 2:
        raise ECGGridDetectionError(
            "ECG grayscale image must be two-dimensional."
        )

    if grayscale.shape != (
        processed_image.height,
        processed_image.width,
    ):
        raise ECGGridDetectionError(
            "ECG grayscale image dimensions do not match metadata."
        )

    if (
        processed_image.width < 10
        or processed_image.height < 10
    ):
        raise ECGGridDetectionError(
            "ECG image is too small for grid detection."
        )

    if not np.all(
        np.isfinite(
            grayscale
        )
    ):
        raise ECGGridDetectionError(
            "ECG grayscale image contains invalid pixel values."
        )

    grayscale = np.clip(
        grayscale,
        0,
        255,
    ).astype(
        np.uint8,
        copy=False,
    )

    return np.ascontiguousarray(
        grayscale
    )


def _validate_positive_number(
    value,
    *,
    name,
):
    if isinstance(
        value,
        bool,
    ):
        raise ECGGridDetectionError(
            f"{name} must be a positive finite number."
        )

    try:
        numeric_value = float(
            value
        )
    except (
        TypeError,
        ValueError,
    ) as exc:
        raise ECGGridDetectionError(
            f"{name} must be a positive finite number."
        ) from exc

    if (
        not math.isfinite(
            numeric_value
        )
        or numeric_value <= 0.0
    ):
        raise ECGGridDetectionError(
            f"{name} must be a positive finite number."
        )

    return numeric_value


def _validate_ratio(
    value,
    *,
    name,
):
    numeric_value = _validate_positive_number(
        value,
        name=name,
    )

    if numeric_value > 1.0:
        raise ECGGridDetectionError(
            f"{name} must be between 0 and 1."
        )

    return numeric_value


def _validate_min_line_count(
    value,
):
    if (
        isinstance(
            value,
            bool,
        )
        or not isinstance(
            value,
            int,
        )
        or value < 3
    ):
        raise ECGGridDetectionError(
            "ECG grid minimum line count must be an integer "
            "greater than or equal to 3."
        )

    return value


def _validate_detection_parameters(
    *,
    min_contrast,
    peak_ratio,
    min_line_count,
    min_spacing_pixels,
    axis_tolerance_ratio,
    interval_tolerance_ratio,
):
    min_contrast = _validate_positive_number(
        min_contrast,
        name="ECG grid minimum contrast",
    )

    peak_ratio = _validate_ratio(
        peak_ratio,
        name="ECG grid peak ratio",
    )

    min_line_count = _validate_min_line_count(
        min_line_count
    )

    min_spacing_pixels = _validate_positive_number(
        min_spacing_pixels,
        name="ECG grid minimum spacing",
    )

    axis_tolerance_ratio = _validate_ratio(
        axis_tolerance_ratio,
        name="ECG grid axis tolerance ratio",
    )

    interval_tolerance_ratio = _validate_ratio(
        interval_tolerance_ratio,
        name="ECG grid interval tolerance ratio",
    )

    return (
        min_contrast,
        peak_ratio,
        min_line_count,
        min_spacing_pixels,
        axis_tolerance_ratio,
        interval_tolerance_ratio,
    )


def _build_line_profile(
    grayscale,
    *,
    axis,
):
    if axis == "x":
        median_intensity = np.median(
            grayscale,
            axis=0,
        )
    elif axis == "y":
        median_intensity = np.median(
            grayscale,
            axis=1,
        )
    else:
        raise ECGGridDetectionError(
            "Unsupported ECG grid detection axis."
        )

    background_level = float(
        np.percentile(
            median_intensity,
            90,
        )
    )

    profile = (
        background_level
        - median_intensity.astype(
            np.float64
        )
    )

    profile = np.maximum(
        profile,
        0.0,
    )

    return profile


def _weighted_group_center(
    profile,
    start,
    end,
):
    indexes = np.arange(
        start,
        end + 1,
        dtype=np.float64,
    )

    weights = profile[
        start:end + 1
    ].astype(
        np.float64
    )

    weight_sum = float(
        np.sum(
            weights
        )
    )

    if weight_sum <= 0.0:
        return float(
            (
                start
                + end
            )
            / 2.0
        )

    return float(
        np.sum(
            indexes
            * weights
        )
        / weight_sum
    )


def _group_peak_positions(
    profile,
    *,
    min_contrast,
    peak_ratio,
):
    if profile.size == 0:
        return tuple()

    maximum_score = float(
        np.max(
            profile
        )
    )

    if maximum_score < min_contrast:
        return tuple()

    threshold = max(
        min_contrast,
        maximum_score * peak_ratio,
    )

    active = (
        profile
        >= threshold
    )

    positions = []
    start = None

    for index, is_active in enumerate(
        active
    ):
        if is_active and start is None:
            start = index
            continue

        if (
            not is_active
            and start is not None
        ):
            positions.append(
                _weighted_group_center(
                    profile,
                    start,
                    index - 1,
                )
            )
            start = None

    if start is not None:
        positions.append(
            _weighted_group_center(
                profile,
                start,
                len(
                    profile
                ) - 1,
            )
        )

    return tuple(
        positions
    )


def _estimate_grid_spacing(
    line_positions,
    *,
    min_line_count,
    min_spacing_pixels,
    interval_tolerance_ratio,
    axis_name,
):
    if len(
        line_positions
    ) < min_line_count:
        raise ECGGridDetectionError(
            f"Too few repeated ECG grid lines were detected "
            f"along the {axis_name}-axis."
        )

    positions = np.asarray(
        line_positions,
        dtype=np.float64,
    )

    intervals = np.diff(
        positions
    )

    valid_intervals = intervals[
        intervals
        >= min_spacing_pixels
    ]

    if len(
        valid_intervals
    ) < (
        min_line_count - 1
    ):
        raise ECGGridDetectionError(
            f"Too few usable ECG grid intervals were detected "
            f"along the {axis_name}-axis."
        )

    lower_quartile = float(
        np.percentile(
            valid_intervals,
            25,
        )
    )

    candidate_limit = (
        lower_quartile
        * (
            1.0
            + interval_tolerance_ratio
        )
    )

    base_intervals = valid_intervals[
        valid_intervals
        <= candidate_limit
    ]

    if len(
        base_intervals
    ) < 2:
        base_intervals = valid_intervals

    spacing = float(
        np.median(
            base_intervals
        )
    )

    if (
        not math.isfinite(
            spacing
        )
        or spacing < min_spacing_pixels
    ):
        raise ECGGridDetectionError(
            f"A reliable ECG grid spacing could not be estimated "
            f"along the {axis_name}-axis."
        )

    deviations = np.abs(
        base_intervals
        - spacing
    )

    allowed_deviation = (
        spacing
        * interval_tolerance_ratio
    )

    consistent_intervals = base_intervals[
        deviations
        <= allowed_deviation
    ]

    if len(
        consistent_intervals
    ) < 2:
        raise ECGGridDetectionError(
            f"ECG grid spacing is not sufficiently consistent "
            f"along the {axis_name}-axis."
        )

    return float(
        np.median(
            consistent_intervals
        )
    )


def detect_ecg_grid_scale(
    processed_image,
    *,
    min_contrast=DEFAULT_ECG_GRID_MIN_CONTRAST,
    peak_ratio=DEFAULT_ECG_GRID_PEAK_RATIO,
    min_line_count=DEFAULT_ECG_GRID_MIN_LINE_COUNT,
    min_spacing_pixels=DEFAULT_ECG_GRID_MIN_SPACING_PIXELS,
    axis_tolerance_ratio=DEFAULT_ECG_GRID_AXIS_TOLERANCE_RATIO,
    interval_tolerance_ratio=DEFAULT_ECG_GRID_INTERVAL_TOLERANCE_RATIO,
):
    """
    Estimate ECG image scale from repeated paper grid lines.

    The detector estimates the spacing between adjacent visible
    grid lines along both image axes. It returns pixels-per-mm
    only when the horizontal and vertical estimates are
    sufficiently consistent.

    This is a grid-scale detection foundation. It does not
    perform clinical ECG interpretation.
    """

    grayscale = _validate_processed_image(
        processed_image
    )

    (
        min_contrast,
        peak_ratio,
        min_line_count,
        min_spacing_pixels,
        axis_tolerance_ratio,
        interval_tolerance_ratio,
    ) = _validate_detection_parameters(
        min_contrast=min_contrast,
        peak_ratio=peak_ratio,
        min_line_count=min_line_count,
        min_spacing_pixels=min_spacing_pixels,
        axis_tolerance_ratio=axis_tolerance_ratio,
        interval_tolerance_ratio=interval_tolerance_ratio,
    )

    x_profile = _build_line_profile(
        grayscale,
        axis="x",
    )

    y_profile = _build_line_profile(
        grayscale,
        axis="y",
    )

    x_line_positions = _group_peak_positions(
        x_profile,
        min_contrast=min_contrast,
        peak_ratio=peak_ratio,
    )

    y_line_positions = _group_peak_positions(
        y_profile,
        min_contrast=min_contrast,
        peak_ratio=peak_ratio,
    )

    x_spacing = _estimate_grid_spacing(
        x_line_positions,
        min_line_count=min_line_count,
        min_spacing_pixels=min_spacing_pixels,
        interval_tolerance_ratio=interval_tolerance_ratio,
        axis_name="x",
    )

    y_spacing = _estimate_grid_spacing(
        y_line_positions,
        min_line_count=min_line_count,
        min_spacing_pixels=min_spacing_pixels,
        interval_tolerance_ratio=interval_tolerance_ratio,
        axis_name="y",
    )

    mean_spacing = (
        x_spacing
        + y_spacing
    ) / 2.0

    axis_difference_ratio = (
        abs(
            x_spacing
            - y_spacing
        )
        / mean_spacing
    )

    if (
        axis_difference_ratio
        > axis_tolerance_ratio
    ):
        raise ECGGridDetectionError(
            "Horizontal and vertical ECG grid scales are "
            "not sufficiently consistent."
        )

    return ECGGridDetectionResult(
        pixels_per_mm=mean_spacing,
        x_spacing_pixels=x_spacing,
        y_spacing_pixels=y_spacing,
        x_grid_line_positions=x_line_positions,
        y_grid_line_positions=y_line_positions,
        axis_difference_ratio=axis_difference_ratio,
    )
