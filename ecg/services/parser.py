import csv
import io
import math
from dataclasses import dataclass

from django.conf import settings

from ecg.models import ECGFile


DEFAULT_ECG_CSV_MAX_ROWS = 500_000
DEFAULT_ECG_PARSER_MAX_BYTES = 50 * 1024 * 1024

TIME_COLUMN_NAMES = {
    "time",
    "time_s",
    "time_sec",
    "timestamp",
    "seconds",
    "second",
    "sec",
    "t",
    "sample",
    "sample_index",
    "sample_number",
}


class ECGParseError(ValueError):
    """Raised when an ECG file cannot be parsed safely."""


@dataclass
class ParsedECG:
    source_format: str
    headers: tuple[str, ...]
    signal_names: tuple[str, ...]
    signals: dict[str, tuple[float, ...]]
    row_count: int
    time_values: tuple[float, ...] | None = None
    sampling_frequency_hz: float | None = None

    @property
    def lead_count(self):
        return len(self.signal_names)

    @property
    def duration_seconds(self):
        if self.row_count <= 1:
            return 0.0

        if self.time_values:
            return (
                self.time_values[-1]
                - self.time_values[0]
            )

        if (
            self.sampling_frequency_hz
            and self.sampling_frequency_hz > 0
        ):
            return (
                self.row_count - 1
            ) / self.sampling_frequency_hz

        return None


def _normalize_header(value):
    return value.strip()


def _normalized_header_key(value):
    return (
        value.strip()
        .lower()
        .replace(" ", "_")
        .replace("-", "_")
    )


def _parse_number(
    value,
    column_name,
    row_number,
):
    cleaned_value = value.strip()

    if not cleaned_value:
        raise ECGParseError(
            f"Missing numeric value in column "
            f"'{column_name}' at row {row_number}."
        )

    try:
        number = float(cleaned_value)
    except ValueError as exc:
        raise ECGParseError(
            f"Invalid numeric value in column "
            f"'{column_name}' at row {row_number}."
        ) from exc

    if not math.isfinite(number):
        raise ECGParseError(
            f"Non-finite numeric value in column "
            f"'{column_name}' at row {row_number}."
        )

    return number


def _detect_time_column(headers):
    for index, header in enumerate(headers):
        if (
            _normalized_header_key(header)
            in TIME_COLUMN_NAMES
        ):
            return index

    return None


def _validate_headers(headers):
    if len(headers) < 2:
        raise ECGParseError(
            "The ECG CSV file must contain at least "
            "two columns."
        )

    cleaned_headers = [
        _normalize_header(header)
        for header in headers
    ]

    if any(
        not header
        for header in cleaned_headers
    ):
        raise ECGParseError(
            "The ECG CSV file contains an empty "
            "column name."
        )

    normalized_headers = [
        _normalized_header_key(header)
        for header in cleaned_headers
    ]

    if len(
        set(normalized_headers)
    ) != len(normalized_headers):
        raise ECGParseError(
            "The ECG CSV file contains duplicate "
            "column names."
        )

    return cleaned_headers


def _read_csv_bytes(ecg_file):
    max_bytes = getattr(
        settings,
        "ECG_PARSER_MAX_BYTES",
        DEFAULT_ECG_PARSER_MAX_BYTES,
    )

    try:
        with ecg_file.file.open("rb") as file_handle:
            content = file_handle.read(
                max_bytes + 1
            )
    except (OSError, ValueError) as exc:
        raise ECGParseError(
            "The ECG file could not be opened."
        ) from exc

    if not content:
        raise ECGParseError(
            "The ECG file is empty."
        )

    if len(content) > max_bytes:
        raise ECGParseError(
            "The ECG file is too large to parse."
        )

    if b"\x00" in content:
        raise ECGParseError(
            "The ECG CSV file contains binary data."
        )

    return content


def _decode_csv_content(content):
    try:
        return content.decode(
            "utf-8-sig"
        )
    except UnicodeDecodeError as exc:
        raise ECGParseError(
            "The ECG CSV file must contain "
            "valid UTF-8 text."
        ) from exc


def _detect_csv_dialect(text):
    sample = text[:8192]

    try:
        return csv.Sniffer().sniff(
            sample,
            delimiters=",;\t|",
        )
    except csv.Error as exc:
        raise ECGParseError(
            "The ECG file does not contain "
            "recognizable CSV data."
        ) from exc


def parse_csv_ecg(ecg_file):
    if not isinstance(
        ecg_file,
        ECGFile,
    ):
        raise ECGParseError(
            "A valid ECGFile instance is required."
        )

    if (
        ecg_file.kind
        != ECGFile.FileKind.CSV
    ):
        raise ECGParseError(
            "This parser only accepts ECG files "
            "with CSV file kind."
        )

    content = _read_csv_bytes(
        ecg_file
    )

    text = _decode_csv_content(
        content
    )

    dialect = _detect_csv_dialect(
        text
    )

    reader = csv.reader(
        io.StringIO(text),
        dialect,
    )

    try:
        raw_headers = next(reader)
    except StopIteration as exc:
        raise ECGParseError(
            "The ECG CSV file does not contain "
            "a header row."
        ) from exc

    headers = _validate_headers(
        raw_headers
    )

    time_column_index = (
        _detect_time_column(
            headers
        )
    )

    signal_indexes = [
        index
        for index in range(
            len(headers)
        )
        if index != time_column_index
    ]

    if not signal_indexes:
        raise ECGParseError(
            "The ECG CSV file does not contain "
            "any signal columns."
        )

    signal_names = [
        headers[index]
        for index in signal_indexes
    ]

    signal_values = {
        signal_name: []
        for signal_name in signal_names
    }

    time_values = (
        []
        if time_column_index is not None
        else None
    )

    max_rows = getattr(
        settings,
        "ECG_CSV_MAX_ROWS",
        DEFAULT_ECG_CSV_MAX_ROWS,
    )

    row_count = 0
    previous_time = None

    for row_number, row in enumerate(
        reader,
        start=2,
    ):
        if not row or all(
            not cell.strip()
            for cell in row
        ):
            continue

        if len(row) != len(headers):
            raise ECGParseError(
                f"Row {row_number} contains "
                f"{len(row)} columns; "
                f"{len(headers)} were expected."
            )

        row_count += 1

        if row_count > max_rows:
            raise ECGParseError(
                "The ECG CSV file contains too "
                "many rows to parse safely."
            )

        if time_column_index is not None:
            current_time = _parse_number(
                row[time_column_index],
                headers[time_column_index],
                row_number,
            )

            if (
                previous_time is not None
                and current_time <= previous_time
            ):
                raise ECGParseError(
                    "ECG time values must be "
                    "strictly increasing."
                )

            time_values.append(
                current_time
            )

            previous_time = current_time

        for signal_index in signal_indexes:
            signal_name = headers[
                signal_index
            ]

            signal_value = _parse_number(
                row[signal_index],
                signal_name,
                row_number,
            )

            signal_values[
                signal_name
            ].append(
                signal_value
            )

    if row_count == 0:
        raise ECGParseError(
            "The ECG CSV file does not contain "
            "any signal samples."
        )

    sampling_frequency_hz = (
        ecg_file.record.sampling_frequency_hz
    )

    return ParsedECG(
        source_format="csv",
        headers=tuple(
            headers
        ),
        signal_names=tuple(
            signal_names
        ),
        signals={
            signal_name: tuple(values)
            for signal_name, values
            in signal_values.items()
        },
        row_count=row_count,
        time_values=(
            tuple(time_values)
            if time_values is not None
            else None
        ),
        sampling_frequency_hz=(
            float(sampling_frequency_hz)
            if sampling_frequency_hz
            else None
        ),
    )