from dataclasses import dataclass

import cv2
import numpy as np

from ecg.services.image_processing import (
    ProcessedECGImage,
)
from ecg.services.perspective import (
    ECGImageQuadrilateral,
)


DEFAULT_ECG_PAPER_MIN_AREA_RATIO = 0.20
DEFAULT_ECG_PAPER_APPROX_EPSILON_RATIO = 0.02

DEFAULT_ECG_PAPER_CANNY_LOW_THRESHOLD = 50
DEFAULT_ECG_PAPER_CANNY_HIGH_THRESHOLD = 150


class ECGPaperDetectionError(ValueError):
    """Raised when ECG paper corners cannot be detected safely."""


@dataclass(frozen=True)
class ECGPaperDetectionResult:
    corners: ECGImageQuadrilateral
    contour_area: float
    image_area: int
    area_ratio: float
    candidate_count: int

    @property
    def top_left(self):
        return self.corners.top_left

    @property
    def top_right(self):
        return self.corners.top_right

    @property
    def bottom_right(self):
        return self.corners.bottom_right

    @property
    def bottom_left(self):
        return self.corners.bottom_left


def _validate_processed_image(
    processed_image,
):
    if not isinstance(
        processed_image,
        ProcessedECGImage,
    ):
        raise ECGPaperDetectionError(
            "Expected ProcessedECGImage."
        )

    grayscale = np.asarray(
        processed_image.grayscale
    )

    if grayscale.ndim != 2:
        raise ECGPaperDetectionError(
            "ECG grayscale image must be two-dimensional."
        )

    if grayscale.shape != (
        processed_image.height,
        processed_image.width,
    ):
        raise ECGPaperDetectionError(
            "ECG grayscale image dimensions do not match metadata."
        )

    if (
        processed_image.width < 5
        or processed_image.height < 5
    ):
        raise ECGPaperDetectionError(
            "ECG image is too small for paper detection."
        )

    if not np.all(
        np.isfinite(
            grayscale
        )
    ):
        raise ECGPaperDetectionError(
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


def _validate_ratio(
    value,
    *,
    name,
    allow_one,
):
    if isinstance(
        value,
        bool,
    ):
        raise ECGPaperDetectionError(
            f"{name} must be numeric."
        )

    try:
        numeric_value = float(
            value
        )
    except (
        TypeError,
        ValueError,
    ) as exc:
        raise ECGPaperDetectionError(
            f"{name} must be numeric."
        ) from exc

    if not np.isfinite(
        numeric_value
    ):
        raise ECGPaperDetectionError(
            f"{name} must be finite."
        )

    if allow_one:
        valid = (
            0.0
            < numeric_value
            <= 1.0
        )
    else:
        valid = (
            0.0
            < numeric_value
            < 1.0
        )

    if not valid:
        raise ECGPaperDetectionError(
            f"{name} must be between 0 and 1."
        )

    return numeric_value


def _validate_detection_parameters(
    *,
    min_area_ratio,
    approx_epsilon_ratio,
):
    min_area_ratio = _validate_ratio(
        min_area_ratio,
        name="ECG paper minimum area ratio",
        allow_one=True,
    )

    approx_epsilon_ratio = _validate_ratio(
        approx_epsilon_ratio,
        name="ECG paper approximation ratio",
        allow_one=False,
    )

    return (
        min_area_ratio,
        approx_epsilon_ratio,
    )


def _detect_edges(
    grayscale,
):
    blurred = cv2.GaussianBlur(
        grayscale,
        (
            5,
            5,
        ),
        0,
    )

    edges = cv2.Canny(
        blurred,
        DEFAULT_ECG_PAPER_CANNY_LOW_THRESHOLD,
        DEFAULT_ECG_PAPER_CANNY_HIGH_THRESHOLD,
    )

    kernel = np.ones(
        (
            5,
            5,
        ),
        dtype=np.uint8,
    )

    closed_edges = cv2.morphologyEx(
        edges,
        cv2.MORPH_CLOSE,
        kernel,
        iterations=2,
    )

    return closed_edges


def _find_contours(
    edge_image,
):
    contours, _ = cv2.findContours(
        edge_image,
        cv2.RETR_EXTERNAL,
        cv2.CHAIN_APPROX_SIMPLE,
    )

    return sorted(
        contours,
        key=cv2.contourArea,
        reverse=True,
    )


def _order_corner_points(
    points,
):
    points = np.asarray(
        points,
        dtype=np.float64,
    )

    if points.shape != (
        4,
        2,
    ):
        raise ECGPaperDetectionError(
            "Detected ECG paper must contain exactly four corners."
        )

    if len(
        {
            (
                float(point[0]),
                float(point[1]),
            )
            for point in points
        }
    ) != 4:
        raise ECGPaperDetectionError(
            "Detected ECG paper corners must be distinct."
        )

    center = np.mean(
        points,
        axis=0,
    )

    angles = np.arctan2(
        points[:, 1] - center[1],
        points[:, 0] - center[0],
    )

    ordered = points[
        np.argsort(
            angles
        )
    ]

    top_left_index = int(
        np.argmin(
            ordered.sum(
                axis=1
            )
        )
    )

    ordered = np.roll(
        ordered,
        -top_left_index,
        axis=0,
    )

    return ECGImageQuadrilateral(
        top_left=(
            float(
                ordered[0][0]
            ),
            float(
                ordered[0][1]
            ),
        ),
        top_right=(
            float(
                ordered[1][0]
            ),
            float(
                ordered[1][1]
            ),
        ),
        bottom_right=(
            float(
                ordered[2][0]
            ),
            float(
                ordered[2][1]
            ),
        ),
        bottom_left=(
            float(
                ordered[3][0]
            ),
            float(
                ordered[3][1]
            ),
        ),
    )


def _collect_quadrilateral_candidates(
    contours,
    *,
    image_area,
    min_area_ratio,
    approx_epsilon_ratio,
):
    candidates = []

    for contour in contours:
        contour_area = float(
            abs(
                cv2.contourArea(
                    contour
                )
            )
        )

        if contour_area <= 0.0:
            continue

        area_ratio = (
            contour_area
            / image_area
        )

        if (
            area_ratio
            < min_area_ratio
        ):
            continue

        perimeter = float(
            cv2.arcLength(
                contour,
                True,
            )
        )

        if perimeter <= 0.0:
            continue

        approximation = cv2.approxPolyDP(
            contour,
            approx_epsilon_ratio
            * perimeter,
            True,
        )

        if len(
            approximation
        ) != 4:
            continue

        if not cv2.isContourConvex(
            approximation
        ):
            continue

        points = approximation.reshape(
            4,
            2,
        )

        try:
            corners = _order_corner_points(
                points
            )
        except ECGPaperDetectionError:
            continue

        candidates.append(
            (
                contour_area,
                area_ratio,
                corners,
            )
        )

    return candidates


def detect_ecg_paper_corners(
    processed_image,
    *,
    min_area_ratio=DEFAULT_ECG_PAPER_MIN_AREA_RATIO,
    approx_epsilon_ratio=DEFAULT_ECG_PAPER_APPROX_EPSILON_RATIO,
):
    """
    Detect the four visible corners of an ECG paper image.

    The function searches for a large convex quadrilateral
    that may represent the visible ECG paper boundary.

    It does not perform perspective correction.
    It only detects and returns the paper corners.
    """

    grayscale = _validate_processed_image(
        processed_image
    )

    (
        min_area_ratio,
        approx_epsilon_ratio,
    ) = _validate_detection_parameters(
        min_area_ratio=min_area_ratio,
        approx_epsilon_ratio=approx_epsilon_ratio,
    )

    edge_image = _detect_edges(
        grayscale
    )

    contours = _find_contours(
        edge_image
    )

    if not contours:
        raise ECGPaperDetectionError(
            "No usable ECG paper boundaries were detected."
        )

    image_area = (
        processed_image.width
        * processed_image.height
    )

    candidates = _collect_quadrilateral_candidates(
        contours,
        image_area=image_area,
        min_area_ratio=min_area_ratio,
        approx_epsilon_ratio=approx_epsilon_ratio,
    )

    if not candidates:
        raise ECGPaperDetectionError(
            "A reliable four-corner ECG paper boundary "
            "could not be detected."
        )

    candidates.sort(
        key=lambda candidate: candidate[0],
        reverse=True,
    )

    (
        contour_area,
        area_ratio,
        corners,
    ) = candidates[0]

    return ECGPaperDetectionResult(
        corners=corners,
        contour_area=contour_area,
        image_area=image_area,
        area_ratio=area_ratio,
        candidate_count=len(
            candidates
        ),
    )