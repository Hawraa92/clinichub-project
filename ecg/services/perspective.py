from dataclasses import dataclass
import math

import numpy as np

from ecg.services.image_processing import ProcessedECGImage


DEFAULT_ECG_PERSPECTIVE_MAX_PIXELS = 40_000_000


class ECGPerspectiveCorrectionError(ValueError):
    """Raised when ECG image perspective correction cannot be completed safely."""


@dataclass(frozen=True)
class ECGImageQuadrilateral:
    top_left: tuple[float, float]
    top_right: tuple[float, float]
    bottom_right: tuple[float, float]
    bottom_left: tuple[float, float]

    @property
    def points(self):
        return (
            self.top_left,
            self.top_right,
            self.bottom_right,
            self.bottom_left,
        )


@dataclass(frozen=True)
class RectifiedECGImage:
    width: int
    height: int
    grayscale: np.ndarray
    source_corners: ECGImageQuadrilateral
    homography: np.ndarray

    @property
    def shape(self):
        return self.grayscale.shape

    @property
    def pixel_count(self):
        return self.width * self.height


def _validate_processed_image(processed_image):
    if not isinstance(processed_image, ProcessedECGImage):
        raise ECGPerspectiveCorrectionError(
            "Expected ProcessedECGImage."
        )

    grayscale = np.asarray(processed_image.grayscale)

    if grayscale.ndim != 2:
        raise ECGPerspectiveCorrectionError(
            "ECG grayscale image must be two-dimensional."
        )

    if grayscale.shape != (
        processed_image.height,
        processed_image.width,
    ):
        raise ECGPerspectiveCorrectionError(
            "ECG grayscale image dimensions do not match metadata."
        )

    if (
        processed_image.width < 2
        or processed_image.height < 2
    ):
        raise ECGPerspectiveCorrectionError(
            "ECG image is too small for perspective correction."
        )

    return grayscale


def _validate_coordinate(value):
    if isinstance(value, bool):
        raise ECGPerspectiveCorrectionError(
            "ECG corner coordinates must be finite numbers."
        )

    try:
        numeric_value = float(value)
    except (TypeError, ValueError) as exc:
        raise ECGPerspectiveCorrectionError(
            "ECG corner coordinates must be finite numbers."
        ) from exc

    if not math.isfinite(numeric_value):
        raise ECGPerspectiveCorrectionError(
            "ECG corner coordinates must be finite numbers."
        )

    return numeric_value


def _normalize_point(point):
    if (
        not isinstance(point, (tuple, list))
        or len(point) != 2
    ):
        raise ECGPerspectiveCorrectionError(
            "Each ECG corner must contain exactly two coordinates."
        )

    return (
        _validate_coordinate(point[0]),
        _validate_coordinate(point[1]),
    )


def _normalize_corners(
    corners,
    *,
    width,
    height,
):
    if not isinstance(corners, ECGImageQuadrilateral):
        raise ECGPerspectiveCorrectionError(
            "Expected ECGImageQuadrilateral."
        )

    normalized_points = tuple(
        _normalize_point(point)
        for point in corners.points
    )

    for x_coordinate, y_coordinate in normalized_points:
        if not (
            0.0
            <= x_coordinate
            <= width - 1
        ):
            raise ECGPerspectiveCorrectionError(
                "ECG corner lies outside the image width."
            )

        if not (
            0.0
            <= y_coordinate
            <= height - 1
        ):
            raise ECGPerspectiveCorrectionError(
                "ECG corner lies outside the image height."
            )

    normalized_corners = ECGImageQuadrilateral(
        top_left=normalized_points[0],
        top_right=normalized_points[1],
        bottom_right=normalized_points[2],
        bottom_left=normalized_points[3],
    )

    _validate_convex_quadrilateral(
        normalized_corners
    )

    return normalized_corners


def _cross_product(
    first,
    second,
    third,
):
    first_x, first_y = first
    second_x, second_y = second
    third_x, third_y = third

    return (
        (second_x - first_x)
        * (third_y - second_y)
        - (second_y - first_y)
        * (third_x - second_x)
    )


def _validate_convex_quadrilateral(corners):
    points = corners.points

    if len(set(points)) != 4:
        raise ECGPerspectiveCorrectionError(
            "ECG image corners must be four distinct points."
        )

    cross_products = []

    for index in range(4):
        first = points[index]

        second = points[
            (index + 1) % 4
        ]

        third = points[
            (index + 2) % 4
        ]

        cross_product = _cross_product(
            first,
            second,
            third,
        )

        if abs(cross_product) < 1e-8:
            raise ECGPerspectiveCorrectionError(
                "ECG image corners must form a non-degenerate quadrilateral."
            )

        cross_products.append(
            cross_product
        )

    has_positive = any(
        value > 0
        for value in cross_products
    )

    has_negative = any(
        value < 0
        for value in cross_products
    )

    if has_positive and has_negative:
        raise ECGPerspectiveCorrectionError(
            "ECG image corners must form a convex quadrilateral "
            "in perimeter order."
        )


def _distance(first, second):
    return math.hypot(
        second[0] - first[0],
        second[1] - first[1],
    )


def _calculate_output_dimensions(corners):
    top_width = _distance(
        corners.top_left,
        corners.top_right,
    )

    bottom_width = _distance(
        corners.bottom_left,
        corners.bottom_right,
    )

    left_height = _distance(
        corners.top_left,
        corners.bottom_left,
    )

    right_height = _distance(
        corners.top_right,
        corners.bottom_right,
    )

    output_width = (
        int(
            round(
                max(
                    top_width,
                    bottom_width,
                )
            )
        )
        + 1
    )

    output_height = (
        int(
            round(
                max(
                    left_height,
                    right_height,
                )
            )
        )
        + 1
    )

    if (
        output_width < 2
        or output_height < 2
    ):
        raise ECGPerspectiveCorrectionError(
            "Corrected ECG image would be too small."
        )

    if (
        output_width
        * output_height
        > DEFAULT_ECG_PERSPECTIVE_MAX_PIXELS
    ):
        raise ECGPerspectiveCorrectionError(
            "Corrected ECG image would exceed the safe pixel limit."
        )

    return (
        output_width,
        output_height,
    )


def _compute_homography(
    source_points,
    destination_points,
):
    matrix_rows = []
    target_values = []

    for (
        source_x,
        source_y,
    ), (
        destination_x,
        destination_y,
    ) in zip(
        source_points,
        destination_points,
    ):
        matrix_rows.append(
            [
                source_x,
                source_y,
                1.0,
                0.0,
                0.0,
                0.0,
                -destination_x * source_x,
                -destination_x * source_y,
            ]
        )

        target_values.append(
            destination_x
        )

        matrix_rows.append(
            [
                0.0,
                0.0,
                0.0,
                source_x,
                source_y,
                1.0,
                -destination_y * source_x,
                -destination_y * source_y,
            ]
        )

        target_values.append(
            destination_y
        )

    matrix = np.asarray(
        matrix_rows,
        dtype=np.float64,
    )

    targets = np.asarray(
        target_values,
        dtype=np.float64,
    )

    try:
        coefficients = np.linalg.solve(
            matrix,
            targets,
        )
    except np.linalg.LinAlgError as exc:
        raise ECGPerspectiveCorrectionError(
            "ECG perspective transformation could not be solved."
        ) from exc

    homography = np.array(
        [
            [
                coefficients[0],
                coefficients[1],
                coefficients[2],
            ],
            [
                coefficients[3],
                coefficients[4],
                coefficients[5],
            ],
            [
                coefficients[6],
                coefficients[7],
                1.0,
            ],
        ],
        dtype=np.float64,
    )

    if not np.all(
        np.isfinite(homography)
    ):
        raise ECGPerspectiveCorrectionError(
            "ECG perspective transformation is not finite."
        )

    return homography


def _warp_grayscale_image(
    grayscale,
    *,
    homography,
    output_width,
    output_height,
):
    try:
        inverse_homography = np.linalg.inv(
            homography
        )
    except np.linalg.LinAlgError as exc:
        raise ECGPerspectiveCorrectionError(
            "ECG perspective transformation cannot be inverted."
        ) from exc

    destination_y, destination_x = np.indices(
        (
            output_height,
            output_width,
        ),
        dtype=np.float64,
    )

    destination_points = np.stack(
        (
            destination_x.ravel(),
            destination_y.ravel(),
            np.ones(
                output_width * output_height,
                dtype=np.float64,
            ),
        )
    )

    source_points = (
        inverse_homography
        @ destination_points
    )

    denominator = source_points[2]

    valid_denominator = (
        np.abs(denominator)
        > 1e-12
    )

    source_x = np.full(
        denominator.shape,
        np.nan,
        dtype=np.float64,
    )

    source_y = np.full(
        denominator.shape,
        np.nan,
        dtype=np.float64,
    )

    source_x[valid_denominator] = (
        source_points[
            0,
            valid_denominator,
        ]
        / denominator[
            valid_denominator
        ]
    )

    source_y[valid_denominator] = (
        source_points[
            1,
            valid_denominator,
        ]
        / denominator[
            valid_denominator
        ]
    )

    source_height, source_width = (
        grayscale.shape
    )

    valid_points = (
        np.isfinite(source_x)
        & np.isfinite(source_y)
        & (source_x >= 0.0)
        & (source_x <= source_width - 1)
        & (source_y >= 0.0)
        & (source_y <= source_height - 1)
    )

    output = np.full(
        output_width * output_height,
        255.0,
        dtype=np.float64,
    )

    if np.any(valid_points):
        x_values = source_x[
            valid_points
        ]

        y_values = source_y[
            valid_points
        ]

        x0 = np.floor(
            x_values
        ).astype(
            np.int64
        )

        y0 = np.floor(
            y_values
        ).astype(
            np.int64
        )

        x1 = np.minimum(
            x0 + 1,
            source_width - 1,
        )

        y1 = np.minimum(
            y0 + 1,
            source_height - 1,
        )

        x_weight = (
            x_values - x0
        )

        y_weight = (
            y_values - y0
        )

        top_left_values = grayscale[
            y0,
            x0,
        ].astype(
            np.float64
        )

        top_right_values = grayscale[
            y0,
            x1,
        ].astype(
            np.float64
        )

        bottom_left_values = grayscale[
            y1,
            x0,
        ].astype(
            np.float64
        )

        bottom_right_values = grayscale[
            y1,
            x1,
        ].astype(
            np.float64
        )

        top_values = (
            top_left_values
            * (1.0 - x_weight)
            + top_right_values
            * x_weight
        )

        bottom_values = (
            bottom_left_values
            * (1.0 - x_weight)
            + bottom_right_values
            * x_weight
        )

        interpolated_values = (
            top_values
            * (1.0 - y_weight)
            + bottom_values
            * y_weight
        )

        output[
            valid_points
        ] = interpolated_values

    output = np.clip(
        np.rint(output),
        0,
        255,
    ).astype(
        np.uint8
    )

    return output.reshape(
        (
            output_height,
            output_width,
        )
    )


def correct_ecg_perspective(
    processed_image,
    *,
    corners,
):
    """
    Rectify an ECG image using four known paper corners.

    Corners must be supplied in this order:
    top-left, top-right, bottom-right, bottom-left.

    This function does not detect paper corners automatically.
    It only performs the geometric correction after valid
    corners have been supplied.
    """

    grayscale = _validate_processed_image(
        processed_image
    )

    normalized_corners = _normalize_corners(
        corners,
        width=processed_image.width,
        height=processed_image.height,
    )

    (
        output_width,
        output_height,
    ) = _calculate_output_dimensions(
        normalized_corners
    )

    source_points = np.asarray(
        normalized_corners.points,
        dtype=np.float64,
    )

    destination_points = np.asarray(
        (
            (
                0.0,
                0.0,
            ),
            (
                output_width - 1.0,
                0.0,
            ),
            (
                output_width - 1.0,
                output_height - 1.0,
            ),
            (
                0.0,
                output_height - 1.0,
            ),
        ),
        dtype=np.float64,
    )

    homography = _compute_homography(
        source_points,
        destination_points,
    )

    rectified_grayscale = _warp_grayscale_image(
        grayscale,
        homography=homography,
        output_width=output_width,
        output_height=output_height,
    )

    return RectifiedECGImage(
        width=output_width,
        height=output_height,
        grayscale=rectified_grayscale,
        source_corners=normalized_corners,
        homography=homography,
    )