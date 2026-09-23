import io
from dataclasses import dataclass

import numpy as np
from PIL import Image, ImageOps, UnidentifiedImageError

from django.conf import settings

from ecg.models import ECGFile


DEFAULT_ECG_IMAGE_MAX_BYTES = 50 * 1024 * 1024
DEFAULT_ECG_IMAGE_MAX_PIXELS = 40_000_000


class ECGImageProcessingError(ValueError):
    """Raised when an ECG image cannot be processed safely."""


@dataclass
class ProcessedECGImage:
    width: int
    height: int
    source_mode: str
    grayscale: np.ndarray

    @property
    def pixel_count(self):
        return self.width * self.height

    @property
    def shape(self):
        return self.grayscale.shape


def _read_image_bytes(ecg_file):
    max_bytes = getattr(
        settings,
        "ECG_IMAGE_PROCESSING_MAX_BYTES",
        DEFAULT_ECG_IMAGE_MAX_BYTES,
    )

    try:
        with ecg_file.file.open("rb") as file_handle:
            content = file_handle.read(
                max_bytes + 1
            )
    except (OSError, ValueError) as exc:
        raise ECGImageProcessingError(
            "The ECG image file could not be opened."
        ) from exc

    if not content:
        raise ECGImageProcessingError(
            "The ECG image file is empty."
        )

    if len(content) > max_bytes:
        raise ECGImageProcessingError(
            "The ECG image file is too large to process."
        )

    return content


def _open_image(content):
    try:
        image = Image.open(
            io.BytesIO(content)
        )

        image.verify()

        image = Image.open(
            io.BytesIO(content)
        )

    except (
        UnidentifiedImageError,
        OSError,
        SyntaxError,
    ) as exc:
        raise ECGImageProcessingError(
            "The uploaded file is not a valid supported image."
        ) from exc

    return image


def _validate_dimensions(image):
    width, height = image.size

    if width <= 0 or height <= 0:
        raise ECGImageProcessingError(
            "The ECG image has invalid dimensions."
        )

    max_pixels = getattr(
        settings,
        "ECG_IMAGE_MAX_PIXELS",
        DEFAULT_ECG_IMAGE_MAX_PIXELS,
    )

    pixel_count = width * height

    if pixel_count > max_pixels:
        raise ECGImageProcessingError(
            "The ECG image dimensions are too large to process safely."
        )


def process_ecg_image(ecg_file):
    if not isinstance(
        ecg_file,
        ECGFile,
    ):
        raise ECGImageProcessingError(
            "A valid ECGFile instance is required."
        )

    if (
        ecg_file.kind
        != ECGFile.FileKind.IMAGE
    ):
        raise ECGImageProcessingError(
            "This processor only accepts ECG image files."
        )

    content = _read_image_bytes(
        ecg_file
    )

    image = _open_image(
        content
    )

    _validate_dimensions(
        image
    )

    try:
        image = ImageOps.exif_transpose(
            image
        )

        source_mode = image.mode

        grayscale_image = image.convert(
            "L"
        )

        grayscale = np.asarray(
            grayscale_image,
            dtype=np.uint8,
        )

    except (
        OSError,
        ValueError,
        MemoryError,
    ) as exc:
        raise ECGImageProcessingError(
            "The ECG image could not be prepared for processing."
        ) from exc

    if grayscale.ndim != 2:
        raise ECGImageProcessingError(
            "The ECG image could not be converted to grayscale."
        )

    height, width = grayscale.shape

    if width <= 0 or height <= 0:
        raise ECGImageProcessingError(
            "The processed ECG image is empty."
        )

    return ProcessedECGImage(
        width=width,
        height=height,
        source_mode=source_mode,
        grayscale=grayscale,
    )