from dataclasses import dataclass

from ecg.services.parser import ParsedECG


DEFAULT_WAVEFORM_MAX_POINTS = 5_000


class ECGWaveformError(ValueError):
    """Raised when parsed ECG data cannot be prepared for display."""


@dataclass(frozen=True)
class WaveformLead:
    name: str
    values: tuple[float, ...]


@dataclass(frozen=True)
class ECGWaveform:
    x_values: tuple[float, ...]
    x_unit: str
    leads: tuple[WaveformLead, ...]
    source_sample_count: int
    displayed_sample_count: int
    downsampled: bool


def _validate_parsed_ecg(parsed_ecg):
    if not isinstance(parsed_ecg, ParsedECG):
        raise ECGWaveformError(
            "A valid ParsedECG instance is required."
        )

    if parsed_ecg.row_count <= 0:
        raise ECGWaveformError(
            "The ECG does not contain any samples."
        )

    if not parsed_ecg.signal_names:
        raise ECGWaveformError(
            "The ECG does not contain any signal leads."
        )

    for signal_name in parsed_ecg.signal_names:
        if signal_name not in parsed_ecg.signals:
            raise ECGWaveformError(
                f"Signal '{signal_name}' is missing."
            )

        signal_values = parsed_ecg.signals[signal_name]

        if len(signal_values) != parsed_ecg.row_count:
            raise ECGWaveformError(
                f"Signal '{signal_name}' contains an "
                "unexpected number of samples."
            )

    if parsed_ecg.time_values is not None:
        if len(parsed_ecg.time_values) != parsed_ecg.row_count:
            raise ECGWaveformError(
                "The ECG time axis contains an "
                "unexpected number of samples."
            )


def _build_x_axis(parsed_ecg):
    if parsed_ecg.time_values is not None:
        return (
            tuple(parsed_ecg.time_values),
            "seconds",
        )

    sampling_frequency_hz = parsed_ecg.sampling_frequency_hz

    if (
        sampling_frequency_hz is not None
        and sampling_frequency_hz > 0
    ):
        return (
            tuple(
                index / sampling_frequency_hz
                for index in range(parsed_ecg.row_count)
            ),
            "seconds",
        )

    return (
        tuple(
            float(index)
            for index in range(parsed_ecg.row_count)
        ),
        "sample",
    )


def _build_display_indexes(
    sample_count,
    max_points,
):
    if max_points < 2:
        raise ECGWaveformError(
            "max_points must be at least 2."
        )

    if sample_count <= max_points:
        return tuple(
            range(sample_count)
        )

    last_index = sample_count - 1
    last_display_index = max_points - 1

    indexes = []

    for display_index in range(max_points):
        source_index = round(
            display_index
            * last_index
            / last_display_index
        )

        indexes.append(
            source_index
        )

    return tuple(indexes)


def build_waveform_preview(
    parsed_ecg,
    max_points=DEFAULT_WAVEFORM_MAX_POINTS,
):
    """
    Prepare parsed ECG data for waveform preview display.

    This preview may reduce the number of displayed points.
    It must not be used as the source data for clinical
    interpretation, signal processing, or AI analysis.
    """

    _validate_parsed_ecg(
        parsed_ecg
    )

    x_values, x_unit = _build_x_axis(
        parsed_ecg
    )

    display_indexes = _build_display_indexes(
        parsed_ecg.row_count,
        max_points,
    )

    displayed_x_values = tuple(
        x_values[index]
        for index in display_indexes
    )

    leads = []

    for signal_name in parsed_ecg.signal_names:
        source_values = parsed_ecg.signals[
            signal_name
        ]

        displayed_values = tuple(
            source_values[index]
            for index in display_indexes
        )

        leads.append(
            WaveformLead(
                name=signal_name,
                values=displayed_values,
            )
        )

    displayed_sample_count = len(
        display_indexes
    )

    return ECGWaveform(
        x_values=displayed_x_values,
        x_unit=x_unit,
        leads=tuple(leads),
        source_sample_count=parsed_ecg.row_count,
        displayed_sample_count=displayed_sample_count,
        downsampled=(
            displayed_sample_count
            < parsed_ecg.row_count
        ),
    )