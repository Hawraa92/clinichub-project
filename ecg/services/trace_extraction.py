from dataclasses import dataclass

import numpy as np

from django.conf import settings

from ecg.services.image_processing import ProcessedECGImage


DEFAULT_ECG_TRACE_DARK_THRESHOLD = 120
DEFAULT_ECG_TRACE_GRID_DENSITY = 0.60
DEFAULT_ECG_TRACE_MAX_FOREGROUND_RATIO = 0.50


class ECGTraceExtractionError(ValueError):
    """Raised when ECG trace candidates cannot be extracted safely."""


@dataclass
class ECGTraceCandidates:
    width: int
    height: int
    threshold: int
    candidate_mask: np.ndarray
    foreground_ratio: float
    removed_dense_rows: int
    removed_dense_columns: int

    @property
    def candidate_pixel_count(self):
        return int(
            np.count_nonzero(
                self.candidate_mask
            )
        )

    @property
    def shape(self):
        return self.candidate_mask.shape


def _validate_processed_image(processed_image):
    if not isinstance(
        processed_image,
        ProcessedECGImage,
    ):
        raise ECGTraceExtractionError(
            "A valid ProcessedECGImage instance is required."
        )

    grayscale = processed_image.grayscale

    if not isinstance(
        grayscale,
        np.ndarray,
    ):
        raise ECGTraceExtractionError(
            "The processed ECG image does not contain a valid pixel array."
        )

    if grayscale.ndim != 2:
        raise ECGTraceExtractionError(
            "The ECG image must be a two-dimensional grayscale image."
        )

    if grayscale.size == 0:
        raise ECGTraceExtractionError(
            "The ECG image contains no pixels."
        )

    if (
        grayscale.shape[1]
        != processed_image.width
        or grayscale.shape[0]
        != processed_image.height
    ):
        raise ECGTraceExtractionError(
            "The ECG image dimensions do not match its pixel data."
        )

    return grayscale


def _validate_threshold(value):
    try:
        threshold = int(value)
    except (TypeError, ValueError) as exc:
        raise ECGTraceExtractionError(
            "The ECG trace threshold must be an integer."
        ) from exc

    if threshold < 0 or threshold > 255:
        raise ECGTraceExtractionError(
            "The ECG trace threshold must be between 0 and 255."
        )

    return threshold


def _validate_grid_density(value):
    try:
        density = float(value)
    except (TypeError, ValueError) as exc:
        raise ECGTraceExtractionError(
            "The ECG grid density threshold must be numeric."
        ) from exc

    if density <= 0 or density > 1:
        raise ECGTraceExtractionError(
            "The ECG grid density threshold must be greater than 0 "
            "and no greater than 1."
        )

    return density


def _remove_dense_grid_lines(
    candidate_mask,
    grid_density,
):
    cleaned_mask = candidate_mask.copy()

    row_density = np.mean(
        cleaned_mask,
        axis=1,
    )

    column_density = np.mean(
        cleaned_mask,
        axis=0,
    )

    dense_rows = (
        row_density >= grid_density
    )

    dense_columns = (
        column_density >= grid_density
    )

    if np.any(dense_rows):
        cleaned_mask[
            dense_rows,
            :
        ] = False

    if np.any(dense_columns):
        cleaned_mask[
            :,
            dense_columns,
        ] = False

    return (
        cleaned_mask,
        int(
            np.count_nonzero(
                dense_rows
            )
        ),
        int(
            np.count_nonzero(
                dense_columns
            )
        ),
    )


def extract_trace_candidates(
    processed_image,
):
    grayscale = _validate_processed_image(
        processed_image
    )

    threshold = _validate_threshold(
        getattr(
            settings,
            "ECG_TRACE_DARK_THRESHOLD",
            DEFAULT_ECG_TRACE_DARK_THRESHOLD,
        )
    )

    grid_density = _validate_grid_density(
        getattr(
            settings,
            "ECG_TRACE_GRID_DENSITY",
            DEFAULT_ECG_TRACE_GRID_DENSITY,
        )
    )

    candidate_mask = (
        grayscale <= threshold
    )

    (
        candidate_mask,
        removed_dense_rows,
        removed_dense_columns,
    ) = _remove_dense_grid_lines(
        candidate_mask,
        grid_density,
    )

    candidate_pixel_count = int(
        np.count_nonzero(
            candidate_mask
        )
    )

    if candidate_pixel_count == 0:
        raise ECGTraceExtractionError(
            "No ECG trace candidates were detected in the image."
        )

    foreground_ratio = (
        candidate_pixel_count
        / candidate_mask.size
    )

    max_foreground_ratio = float(
        getattr(
            settings,
            "ECG_TRACE_MAX_FOREGROUND_RATIO",
            DEFAULT_ECG_TRACE_MAX_FOREGROUND_RATIO,
        )
    )

    if (
        max_foreground_ratio <= 0
        or max_foreground_ratio > 1
    ):
        raise ECGTraceExtractionError(
            "The ECG foreground ratio limit is invalid."
        )

    if foreground_ratio > max_foreground_ratio:
        raise ECGTraceExtractionError(
            "Too much of the image was classified as ECG foreground."
        )

    return ECGTraceCandidates(
        width=processed_image.width,
        height=processed_image.height,
        threshold=threshold,
        candidate_mask=candidate_mask,
        foreground_ratio=foreground_ratio,
        removed_dense_rows=removed_dense_rows,
        removed_dense_columns=removed_dense_columns,
    )