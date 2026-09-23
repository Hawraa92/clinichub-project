import io
import tempfile

import numpy as np
from PIL import Image

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings

from appointments.tests.factories import AppointmentFactory
from ecg.models import ECGFile, ECGRecord
from ecg.services.image_processing import (
    ECGImageProcessingError,
    process_ecg_image,
)


class ECGImageProcessingTests(TestCase):
    def setUp(self):
        self.private_media = tempfile.TemporaryDirectory()

        self.settings_override = override_settings(
            PRIVATE_MEDIA_ROOT=self.private_media.name,
        )
        self.settings_override.enable()

        self.appointment = AppointmentFactory()

        self.record = ECGRecord.objects.create(
            patient=self.appointment.patient,
            doctor=self.appointment.doctor,
            appointment=self.appointment,
            hospital=self.appointment.hospital,
            branch=self.appointment.branch,
            department=self.appointment.department,
        )

    def tearDown(self):
        self.settings_override.disable()
        self.private_media.cleanup()

    def create_png_bytes(
        self,
        width=4,
        height=3,
    ):
        buffer = io.BytesIO()

        image = Image.new(
            "RGB",
            (width, height),
            color=(
                255,
                255,
                255,
            ),
        )

        image.save(
            buffer,
            format="PNG",
        )

        return buffer.getvalue()

    def create_image_file(
        self,
        content=None,
        filename="ecg.png",
        kind=ECGFile.FileKind.IMAGE,
    ):
        if content is None:
            content = self.create_png_bytes()

        return ECGFile.objects.create(
            record=self.record,
            kind=kind,
            file=SimpleUploadedFile(
                filename,
                content,
                content_type="image/png",
            ),
        )

    def test_valid_ecg_image_is_processed(self):
        ecg_file = self.create_image_file(
            content=self.create_png_bytes(
                width=4,
                height=3,
            )
        )

        processed = process_ecg_image(
            ecg_file
        )

        self.assertEqual(
            processed.width,
            4,
        )

        self.assertEqual(
            processed.height,
            3,
        )

        self.assertEqual(
            processed.source_mode,
            "RGB",
        )

        self.assertEqual(
            processed.shape,
            (
                3,
                4,
            ),
        )

        self.assertEqual(
            processed.pixel_count,
            12,
        )

        self.assertEqual(
            processed.grayscale.dtype,
            np.uint8,
        )

    def test_invalid_image_content_is_rejected(self):
        ecg_file = self.create_image_file(
            content=b"This is not a real image."
        )

        with self.assertRaises(
            ECGImageProcessingError
        ):
            process_ecg_image(
                ecg_file
            )

    def test_non_image_file_kind_is_rejected(self):
        ecg_file = self.create_image_file(
            kind=ECGFile.FileKind.CSV,
        )

        with self.assertRaises(
            ECGImageProcessingError
        ):
            process_ecg_image(
                ecg_file
            )

    @override_settings(
        ECG_IMAGE_MAX_PIXELS=10
    )
    def test_image_with_too_many_pixels_is_rejected(self):
        ecg_file = self.create_image_file(
            content=self.create_png_bytes(
                width=4,
                height=3,
            )
        )

        with self.assertRaises(
            ECGImageProcessingError
        ):
            process_ecg_image(
                ecg_file
            )

    @override_settings(
        ECG_IMAGE_PROCESSING_MAX_BYTES=10
    )
    def test_image_over_processing_size_limit_is_rejected(self):
        ecg_file = self.create_image_file(
            content=self.create_png_bytes()
        )

        with self.assertRaises(
            ECGImageProcessingError
        ):
            process_ecg_image(
                ecg_file
            )