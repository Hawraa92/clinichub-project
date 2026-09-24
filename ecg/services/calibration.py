from dataclasses import dataclass
import math

from ecg.services.signal_reconstruction import (
    ReconstructedECGSignal,
)


DEFAULT_ECG_PAPER_SPEED_MM_PER_S = 25.0
DEFAULT_ECG_GAIN_MM_PER_MV = 10.0


class ECGCalibrationError(ValueError):
    """Raised when ECG pixel-space calibration cannot be completed safely."""


@dataclass(frozen=True)
class ECGCalibrationParameters:
    pixels_per_mm: float
    paper_speed_mm_per_s: float
    gain_mm_per_mv: float


@dataclass(frozen=True)
class CalibratedECGSignal:
    time_seconds: tuple[float, ...]
    amplitude_mv: tuple[float | None, ...]
    parameters: ECGCalibrationParameters

    @property
    def sample_count(self):
        return sum(
            value is not None
            for value in self.amplitude_mv
        )

    @property
    def missing_count(self):
        return len(
            self.amplitude_mv
        ) - self.sample_count

    @property
    def duration_seconds(self):
        if not self.time_seconds:
            return 0.0

        return (
            self.time_seconds[-1]
            - self.time_seconds[0]
        )


def _validate_positive_number(
    value,
    field_name,
):
    if isinstance(
        value,
        bool,
    ):
        raise ECGCalibrationError(
            f"{field_name} must be a positive finite number."
        )

    try:
        numeric_value = float(
            value
        )
    except (
        TypeError,
        ValueError,
    ) as exc:
        raise ECGCalibrationError(
            f"{field_name} must be a positive finite number."
        ) from exc

    if (
        not math.isfinite(
            numeric_value
        )
        or numeric_value <= 0
    ):
        raise ECGCalibrationError(
            f"{field_name} must be a positive finite number."
        )

    return numeric_value


def _validate_reconstructed_signal(
    reconstructed_signal,
):
    if not isinstance(
        reconstructed_signal,
        ReconstructedECGSignal,
    ):
        raise ECGCalibrationError(
            "Expected ReconstructedECGSignal."
        )

    x_positions = reconstructed_signal.x_positions
    signal_values = reconstructed_signal.signal_values

    if not x_positions:
        raise ECGCalibrationError(
            "Reconstructed ECG signal has no x positions."
        )

    if len(
        x_positions
    ) != len(
        signal_values
    ):
        raise ECGCalibrationError(
            "ECG x positions and signal values must have equal length."
        )

    previous_x = None

    for x_position in x_positions:
        if isinstance(
            x_position,
            bool,
        ):
            raise ECGCalibrationError(
                "ECG x positions must be finite numbers."
            )

        try:
            numeric_x = float(
                x_position
            )
        except (
            TypeError,
            ValueError,
        ) as exc:
            raise ECGCalibrationError(
                "ECG x positions must be finite numbers."
            ) from exc

        if not math.isfinite(
            numeric_x
        ):
            raise ECGCalibrationError(
                "ECG x positions must be finite numbers."
            )

        if (
            previous_x is not None
            and numeric_x <= previous_x
        ):
            raise ECGCalibrationError(
                "ECG x positions must be strictly increasing."
            )

        previous_x = numeric_x

    for signal_value in signal_values:
        if signal_value is None:
            continue

        if isinstance(
            signal_value,
            bool,
        ):
            raise ECGCalibrationError(
                "ECG signal values must be finite numbers or None."
            )

        try:
            numeric_value = float(
                signal_value
            )
        except (
            TypeError,
            ValueError,
        ) as exc:
            raise ECGCalibrationError(
                "ECG signal values must be finite numbers or None."
            ) from exc

        if not math.isfinite(
            numeric_value
        ):
            raise ECGCalibrationError(
                "ECG signal values must be finite numbers or None."
            )


def calibrate_reconstructed_signal(
    reconstructed_signal,
    *,
    pixels_per_mm,
    paper_speed_mm_per_s=DEFAULT_ECG_PAPER_SPEED_MM_PER_S,
    gain_mm_per_mv=DEFAULT_ECG_GAIN_MM_PER_MV,
):
    """
    Convert a reconstructed ECG signal from pixel space into
    time in seconds and amplitude in millivolts.

    This function does not infer calibration from an ECG image.
    The caller must supply a valid pixels-per-millimetre scale.
    """

    _validate_reconstructed_signal(
        reconstructed_signal
    )

    pixels_per_mm = _validate_positive_number(
        pixels_per_mm,
        "pixels_per_mm",
    )

    paper_speed_mm_per_s = _validate_positive_number(
        paper_speed_mm_per_s,
        "paper_speed_mm_per_s",
    )

    gain_mm_per_mv = _validate_positive_number(
        gain_mm_per_mv,
        "gain_mm_per_mv",
    )

    parameters = ECGCalibrationParameters(
        pixels_per_mm=pixels_per_mm,
        paper_speed_mm_per_s=paper_speed_mm_per_s,
        gain_mm_per_mv=gain_mm_per_mv,
    )

    first_x = float(
        reconstructed_signal.x_positions[0]
    )

    time_seconds = []

    for x_position in reconstructed_signal.x_positions:
        pixel_distance = (
            float(
                x_position
            )
            - first_x
        )

        distance_mm = (
            pixel_distance
            / pixels_per_mm
        )

        time_seconds.append(
            distance_mm
            / paper_speed_mm_per_s
        )

    amplitude_mv = []

    for signal_value in reconstructed_signal.signal_values:
        if signal_value is None:
            amplitude_mv.append(
                None
            )
            continue

        amplitude_mm = (
            float(
                signal_value
            )
            / pixels_per_mm
        )

        amplitude_mv.append(
            amplitude_mm
            / gain_mm_per_mv
        )

    return CalibratedECGSignal(
        time_seconds=tuple(
            time_seconds
        ),
        amplitude_mv=tuple(
            amplitude_mv
        ),
        parameters=parameters,
    )