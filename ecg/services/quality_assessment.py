from dataclasses import dataclass
from math import isfinite


DEFAULT_ECG_MIN_USABLE_COVERAGE_RATIO = 0.90
DEFAULT_ECG_HIGH_QUALITY_COVERAGE_RATIO = 0.98
DEFAULT_ECG_MIN_USABLE_SAMPLE_COUNT = 10


class ECGQualityAssessmentError(ValueError):
    """Raised when ECG processing quality cannot be assessed safely."""


@dataclass(frozen=True)
class ECGQualityAssessmentResult:
    usable: bool
    quality_level: str

    coverage_ratio: float
    sample_count: int
    missing_count: int

    layout_detected: bool
    layout_row_count: int
    layout_cell_count: int

    grid_detected: bool
    calibrated: bool

    reasons: tuple[str, ...]
    warnings: tuple[str, ...]

    @property
    def high_quality(self):
        return self.quality_level == "high"

    @property
    def insufficient_quality(self):
        return self.quality_level == "insufficient"

    @property
    def coverage_percent(self):
        return self.coverage_ratio * 100.0


def _validate_ratio(
    value,
    *,
    name,
):
    try:
        value = float(value)
    except (TypeError, ValueError) as exc:
        raise ECGQualityAssessmentError(
            f"{name} must be a numeric value."
        ) from exc

    if not isfinite(value):
        raise ECGQualityAssessmentError(
            f"{name} must be finite."
        )

    if value < 0.0 or value > 1.0:
        raise ECGQualityAssessmentError(
            f"{name} must be between 0 and 1."
        )

    return value


def _validate_positive_integer(
    value,
    *,
    name,
):
    if isinstance(value, bool):
        raise ECGQualityAssessmentError(
            f"{name} must be an integer."
        )

    try:
        value = int(value)
    except (TypeError, ValueError) as exc:
        raise ECGQualityAssessmentError(
            f"{name} must be an integer."
        ) from exc

    if value < 1:
        raise ECGQualityAssessmentError(
            f"{name} must be greater than zero."
        )

    return value


def _validate_non_negative_integer(
    value,
    *,
    name,
):
    if isinstance(value, bool):
        raise ECGQualityAssessmentError(
            f"{name} must be an integer."
        )

    try:
        value = int(value)
    except (TypeError, ValueError) as exc:
        raise ECGQualityAssessmentError(
            f"{name} must be an integer."
        ) from exc

    if value < 0:
        raise ECGQualityAssessmentError(
            f"{name} must not be negative."
        )

    return value


def _get_signal_metrics(
    reconstructed_signal,
):
    if reconstructed_signal is None:
        raise ECGQualityAssessmentError(
            "A reconstructed ECG signal is required."
        )

    try:
        coverage_ratio = reconstructed_signal.coverage_ratio
        sample_count = reconstructed_signal.sample_count
        missing_count = reconstructed_signal.missing_count
    except AttributeError as exc:
        raise ECGQualityAssessmentError(
            "The reconstructed ECG signal does not expose "
            "the required quality metrics."
        ) from exc

    coverage_ratio = _validate_ratio(
        coverage_ratio,
        name="coverage_ratio",
    )

    sample_count = _validate_positive_integer(
        sample_count,
        name="sample_count",
    )

    missing_count = _validate_non_negative_integer(
        missing_count,
        name="missing_count",
    )

    if missing_count > sample_count:
        raise ECGQualityAssessmentError(
            "missing_count cannot exceed sample_count."
        )

    return (
        coverage_ratio,
        sample_count,
        missing_count,
    )


def _get_layout_metrics(
    lead_layout,
):
    if lead_layout is None:
        return (
            False,
            0,
            0,
        )

    try:
        row_count = lead_layout.row_count
        cell_count = lead_layout.cell_count
    except AttributeError as exc:
        raise ECGQualityAssessmentError(
            "The ECG lead layout does not expose "
            "the required layout metrics."
        ) from exc

    row_count = _validate_non_negative_integer(
        row_count,
        name="layout_row_count",
    )

    cell_count = _validate_non_negative_integer(
        cell_count,
        name="layout_cell_count",
    )

    if row_count == 0 or cell_count == 0:
        raise ECGQualityAssessmentError(
            "A detected ECG lead layout must contain "
            "at least one row and one cell."
        )

    return (
        True,
        row_count,
        cell_count,
    )


def _validate_grid_detection(
    grid_detection,
):
    if grid_detection is None:
        return False

    try:
        pixels_per_mm = float(
            grid_detection.pixels_per_mm
        )
    except (AttributeError, TypeError, ValueError) as exc:
        raise ECGQualityAssessmentError(
            "The ECG grid detection result does not expose "
            "a valid pixels_per_mm value."
        ) from exc

    if (
        not isfinite(pixels_per_mm)
        or pixels_per_mm <= 0.0
    ):
        raise ECGQualityAssessmentError(
            "pixels_per_mm must be a positive finite value."
        )

    return True


def _determine_quality_level(
    *,
    usable,
    coverage_ratio,
    missing_count,
    high_quality_coverage_ratio,
):
    if not usable:
        return "insufficient"

    if (
        coverage_ratio >= high_quality_coverage_ratio
        and missing_count == 0
    ):
        return "high"

    return "acceptable"


def assess_ecg_processing_quality(
    reconstructed_signal,
    *,
    lead_layout=None,
    grid_detection=None,
    calibrated_signal=None,
    min_coverage_ratio=DEFAULT_ECG_MIN_USABLE_COVERAGE_RATIO,
    high_quality_coverage_ratio=DEFAULT_ECG_HIGH_QUALITY_COVERAGE_RATIO,
    min_sample_count=DEFAULT_ECG_MIN_USABLE_SAMPLE_COUNT,
    require_layout=False,
    require_grid=False,
    require_calibration=False,
):
    """
    Assess engineering quality of ECG image-processing output.

    This assessment evaluates whether extracted ECG data are sufficiently
    complete for later processing stages. It is not a medical diagnosis,
    clinical confidence estimate, or validation of diagnostic accuracy.
    """

    min_coverage_ratio = _validate_ratio(
        min_coverage_ratio,
        name="min_coverage_ratio",
    )

    high_quality_coverage_ratio = _validate_ratio(
        high_quality_coverage_ratio,
        name="high_quality_coverage_ratio",
    )

    if high_quality_coverage_ratio < min_coverage_ratio:
        raise ECGQualityAssessmentError(
            "high_quality_coverage_ratio cannot be lower "
            "than min_coverage_ratio."
        )

    min_sample_count = _validate_positive_integer(
        min_sample_count,
        name="min_sample_count",
    )

    (
        coverage_ratio,
        sample_count,
        missing_count,
    ) = _get_signal_metrics(
        reconstructed_signal
    )

    (
        layout_detected,
        layout_row_count,
        layout_cell_count,
    ) = _get_layout_metrics(
        lead_layout
    )

    grid_detected = _validate_grid_detection(
        grid_detection
    )

    calibrated = calibrated_signal is not None

    reasons = []
    warnings = []

    if sample_count < min_sample_count:
        reasons.append(
            "The reconstructed ECG signal contains "
            "too few samples."
        )

    if coverage_ratio < min_coverage_ratio:
        reasons.append(
            "The reconstructed ECG signal coverage "
            "is below the minimum usable threshold."
        )

    if require_layout and not layout_detected:
        reasons.append(
            "A detected ECG lead layout is required."
        )

    if require_grid and not grid_detected:
        reasons.append(
            "ECG grid detection is required."
        )

    if require_calibration and not calibrated:
        reasons.append(
            "ECG signal calibration is required."
        )

    if (
        coverage_ratio >= min_coverage_ratio
        and coverage_ratio < high_quality_coverage_ratio
    ):
        warnings.append(
            "The ECG signal is usable but contains "
            "incomplete reconstructed coverage."
        )

    if missing_count > 0:
        warnings.append(
            "The reconstructed ECG signal contains "
            "missing samples."
        )

    usable = not reasons

    quality_level = _determine_quality_level(
        usable=usable,
        coverage_ratio=coverage_ratio,
        missing_count=missing_count,
        high_quality_coverage_ratio=(
            high_quality_coverage_ratio
        ),
    )

    return ECGQualityAssessmentResult(
        usable=usable,
        quality_level=quality_level,
        coverage_ratio=coverage_ratio,
        sample_count=sample_count,
        missing_count=missing_count,
        layout_detected=layout_detected,
        layout_row_count=layout_row_count,
        layout_cell_count=layout_cell_count,
        grid_detected=grid_detected,
        calibrated=calibrated,
        reasons=tuple(reasons),
        warnings=tuple(warnings),
    )