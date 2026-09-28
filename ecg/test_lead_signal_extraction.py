
"""
Tests for ECG Per-Lead Signal Extraction Foundation.

These tests cover:

- Independent extraction of twelve named ECG lead signals.
- Horizontal and vertical cell isolation.
- Preservation of original cell coordinates.
- Local-to-global coordinate conversion.
- Image and lead-identification validation.
- Prevention of overlapping cell extraction.
- Safe handling of extraction and reconstruction failures.

No clinical diagnosis or ECG interpretation is performed here.
"""

from dataclasses import replace
from unittest.mock import patch

import numpy as np

from django.test import SimpleTestCase

from ecg.services.image_processing import ProcessedECGImage

from ecg.services.lead_identification import (
    ECGLeadIdentificationResult,
    identify_ecg_leads,
)

from ecg.services.lead_segmentation import (
    ECGLeadLayoutCell,
    ECGLeadLayoutResult,
    ECGLeadRegion,
)

from ecg.services.lead_signal_extraction import (
    ECGExtractedLeadSignal,
    ECGLeadSignalExtractionError,
    ECGLeadSignalExtractionResult,
    extract_ecg_lead_signals,
)

from ecg.services.signal_reconstruction import (
    ECGSignalReconstructionError,
)

from ecg.services.trace_extraction import (
    ECGTraceExtractionError,
    extract_trace_candidates,
)


class ECGLeadSignalExtractionTests(SimpleTestCase):

    # =========================================================
    # Test Fixtures
    # =========================================================

    def create_processed_image(self):
        """
        Create a synthetic ECG image containing twelve independent
        trace patterns arranged in a 3x4 layout.

        Each cell is 20x12 pixels.
        Full image dimensions are 80x36 pixels.

        Trace shapes differ slightly between cells so spatial
        isolation can be verified.
        """

        width = 80
        height = 36

        grayscale = np.full(
            (height, width),
            255,
            dtype=np.uint8,
        )

        expected_traces = {}

        wave_offsets = (
            0,
            -1,
            -2,
            -1,
            0,
            1,
        )

        for row_index in range(1, 4):
            for column_index in range(1, 5):

                left = (column_index - 1) * 20
                top = (row_index - 1) * 12

                baseline = 3 + (
                    (row_index + column_index) % 3
                )

                local_trace = []

                for local_x in range(20):

                    local_y = (
                        baseline
                        + wave_offsets[
                            local_x % len(wave_offsets)
                        ]
                    )

                    grayscale[
                        top + local_y,
                        left + local_x,
                    ] = 0

                    local_trace.append(local_y)

                expected_traces[
                    (row_index, column_index)
                ] = tuple(local_trace)

        processed_image = ProcessedECGImage(
            width=width,
            height=height,
            source_mode="RGB",
            grayscale=grayscale,
        )

        return processed_image, expected_traces

    def create_lead_identification(self):
        """
        Build a valid twelve-cell layout and explicitly identify
        its lead names using the standard_3x4 template.
        """

        rows = []

        for row_index in range(1, 4):

            top = (row_index - 1) * 12
            bottom = row_index * 12

            rows.append(
                ECGLeadRegion(
                    index=row_index,
                    top=top,
                    bottom=bottom,
                    active_top=top + 1,
                    active_bottom=bottom - 1,
                    candidate_pixel_count=80,
                )
            )

        cells = []
        cell_index = 1

        for row in rows:
            for column_index in range(1, 5):

                left = (column_index - 1) * 20
                right = column_index * 20

                cells.append(
                    ECGLeadLayoutCell(
                        index=cell_index,
                        row_index=row.index,
                        column_index=column_index,
                        left=left,
                        right=right,
                        top=row.top,
                        bottom=row.bottom,
                        active_left=left + 1,
                        active_right=right - 1,
                        active_top=row.active_top,
                        active_bottom=row.active_bottom,
                        candidate_pixel_count=20,
                    )
                )

                cell_index += 1

        layout = ECGLeadLayoutResult(
            width=80,
            height=36,
            rows=tuple(rows),
            cells=tuple(cells),
        )

        return identify_ecg_leads(
            layout,
            layout_format="standard_3x4",
        )

    def create_valid_inputs(self):
        processed_image, expected_traces = (
            self.create_processed_image()
        )

        identification = (
            self.create_lead_identification()
        )

        return (
            processed_image,
            identification,
            expected_traces,
        )

    def change_identified_lead(
        self,
        identification,
        position,
        **changes,
    ):
        """
        Create a modified identification result without changing
        the original frozen dataclass.
        """

        leads = list(identification.leads)

        leads[position] = replace(
            leads[position],
            **changes,
        )

        return replace(
            identification,
            leads=tuple(leads),
        )

    # =========================================================
    # 1. Successful Independent Extraction
    # =========================================================

    def test_extracts_twelve_independent_named_lead_signals(self):
        (
            processed_image,
            identification,
            _,
        ) = self.create_valid_inputs()

        result = extract_ecg_lead_signals(
            processed_image,
            identification,
        )

        self.assertIsInstance(
            result,
            ECGLeadSignalExtractionResult,
        )

        self.assertEqual(
            result.layout_format,
            "standard_3x4",
        )

        self.assertEqual(result.source_width, 80)
        self.assertEqual(result.source_height, 36)

        self.assertEqual(result.lead_count, 12)

        self.assertTrue(result.complete_12_lead)

        self.assertEqual(
            result.lead_names,
            (
                "I",
                "aVR",
                "V1",
                "V4",
                "II",
                "aVL",
                "V2",
                "V5",
                "III",
                "aVF",
                "V3",
                "V6",
            ),
        )

    def test_every_extracted_lead_has_its_own_signal(self):
        (
            processed_image,
            identification,
            _,
        ) = self.create_valid_inputs()

        result = extract_ecg_lead_signals(
            processed_image,
            identification,
        )

        signal_ids = set()

        for lead in result.leads:

            with self.subTest(lead=lead.name):

                self.assertIsInstance(
                    lead,
                    ECGExtractedLeadSignal,
                )

                self.assertEqual(
                    lead.sample_count,
                    20,
                )

                self.assertEqual(
                    lead.missing_count,
                    0,
                )

                self.assertEqual(
                    lead.coverage_ratio,
                    1.0,
                )

                signal_ids.add(
                    id(lead.reconstructed_signal)
                )

        # Twelve different reconstructed signal objects.
        self.assertEqual(len(signal_ids), 12)

    def test_extracted_leads_preserve_original_cell_information(self):
        (
            processed_image,
            identification,
            _,
        ) = self.create_valid_inputs()

        result = extract_ecg_lead_signals(
            processed_image,
            identification,
        )

        for extracted_lead, identified_lead in zip(
            result.leads,
            identification.leads,
        ):

            with self.subTest(lead=extracted_lead.name):

                self.assertEqual(
                    extracted_lead.name,
                    identified_lead.name,
                )

                self.assertEqual(
                    extracted_lead.row_index,
                    identified_lead.row_index,
                )

                self.assertEqual(
                    extracted_lead.column_index,
                    identified_lead.column_index,
                )

                self.assertIs(
                    extracted_lead.cell,
                    identified_lead.cell,
                )

                self.assertEqual(
                    extracted_lead.image_left,
                    identified_lead.cell.left,
                )

                self.assertEqual(
                    extracted_lead.image_top,
                    identified_lead.cell.top,
                )

    # =========================================================
    # 2. Local and Global Coordinates
    # =========================================================

    def test_every_lead_has_correct_local_x_coordinates(self):
        (
            processed_image,
            identification,
            _,
        ) = self.create_valid_inputs()

        result = extract_ecg_lead_signals(
            processed_image,
            identification,
        )

        for lead in result.leads:

            with self.subTest(lead=lead.name):

                self.assertEqual(
                    lead.x_positions_local,
                    tuple(range(20)),
                )

    def test_every_lead_has_correct_global_x_coordinates(self):
        (
            processed_image,
            identification,
            _,
        ) = self.create_valid_inputs()

        result = extract_ecg_lead_signals(
            processed_image,
            identification,
        )

        for lead in result.leads:

            with self.subTest(lead=lead.name):

                expected_x = tuple(
                    lead.cell.left + x
                    for x in range(20)
                )

                self.assertEqual(
                    lead.x_positions_global,
                    expected_x,
                )

    def test_every_lead_has_correct_global_y_coordinates(self):
        (
            processed_image,
            identification,
            expected_traces,
        ) = self.create_valid_inputs()

        result = extract_ecg_lead_signals(
            processed_image,
            identification,
        )

        for lead in result.leads:

            with self.subTest(lead=lead.name):

                expected_local_y = expected_traces[
                    (
                        lead.row_index,
                        lead.column_index,
                    )
                ]

                expected_global_y = tuple(
                    lead.cell.top + y
                    for y in expected_local_y
                )

                self.assertEqual(
                    tuple(
                        lead.reconstructed_signal.y_positions
                    ),
                    expected_local_y,
                )

                self.assertEqual(
                    lead.y_positions_global,
                    expected_global_y,
                )

    # =========================================================
    # 3. Cell Isolation
    # =========================================================

    def test_trace_extraction_receives_individual_cell_images(self):
        (
            processed_image,
            identification,
            _,
        ) = self.create_valid_inputs()

        with patch(
            "ecg.services.lead_signal_extraction.extract_trace_candidates",
            wraps=extract_trace_candidates,
        ) as extraction_mock:

            result = extract_ecg_lead_signals(
                processed_image,
                identification,
            )

        self.assertEqual(result.lead_count, 12)

        self.assertEqual(
            extraction_mock.call_count,
            12,
        )

        for extraction_call in extraction_mock.call_args_list:

            cropped_image = extraction_call.args[0]

            self.assertIsInstance(
                cropped_image,
                ProcessedECGImage,
            )

            self.assertEqual(
                cropped_image.width,
                20,
            )

            self.assertEqual(
                cropped_image.height,
                12,
            )

            self.assertEqual(
                np.asarray(
                    cropped_image.grayscale
                ).shape,
                (12, 20),
            )

    def test_extraction_does_not_modify_original_image(self):
        (
            processed_image,
            identification,
            _,
        ) = self.create_valid_inputs()

        original_pixels = np.array(
            processed_image.grayscale,
            copy=True,
        )

        extract_ecg_lead_signals(
            processed_image,
            identification,
        )

        self.assertTrue(
            np.array_equal(
                processed_image.grayscale,
                original_pixels,
            )
        )

    def test_get_lead_returns_correct_signal(self):
        (
            processed_image,
            identification,
            _,
        ) = self.create_valid_inputs()

        result = extract_ecg_lead_signals(
            processed_image,
            identification,
        )

        lead_i = result.get_lead("I")
        lead_v6 = result.get_lead("V6")

        self.assertIsNotNone(lead_i)
        self.assertIsNotNone(lead_v6)

        self.assertEqual(
            (lead_i.row_index, lead_i.column_index),
            (1, 1),
        )

        self.assertEqual(
            (lead_v6.row_index, lead_v6.column_index),
            (3, 4),
        )

        self.assertIsNone(
            result.get_lead("UNKNOWN")
        )

        self.assertIsNone(
            result.get_lead("V7")
        )

        self.assertEqual(
            len(result.coverage_by_lead),
            12,
        )

        self.assertEqual(
            result.coverage_by_lead["I"],
            1.0,
        )

    # =========================================================
    # 4. Image Input Validation
    # =========================================================

    def test_accepts_flattened_grayscale_image(self):
        (
            processed_image,
            identification,
            _,
        ) = self.create_valid_inputs()

        flattened_image = replace(
            processed_image,
            grayscale=np.asarray(
                processed_image.grayscale
            ).reshape(-1),
        )

        result = extract_ecg_lead_signals(
            flattened_image,
            identification,
        )

        self.assertEqual(result.lead_count, 12)
        self.assertTrue(result.complete_12_lead)

    def test_rejects_invalid_processed_image_type(self):
        identification = (
            self.create_lead_identification()
        )

        with self.assertRaisesRegex(
            ECGLeadSignalExtractionError,
            "A valid ProcessedECGImage is required",
        ):
            extract_ecg_lead_signals(
                "invalid-image",
                identification,
            )

    def test_rejects_non_positive_image_dimensions(self):
        (
            processed_image,
            identification,
            _,
        ) = self.create_valid_inputs()

        invalid_images = (
            replace(processed_image, width=0),
            replace(processed_image, height=0),
        )

        for invalid_image in invalid_images:

            with self.subTest(
                width=invalid_image.width,
                height=invalid_image.height,
            ):

                with self.assertRaisesRegex(
                    ECGLeadSignalExtractionError,
                    "dimensions must be positive",
                ):
                    extract_ecg_lead_signals(
                        invalid_image,
                        identification,
                    )

    def test_rejects_invalid_grayscale_shape(self):
        (
            processed_image,
            identification,
            _,
        ) = self.create_valid_inputs()

        invalid_image = replace(
            processed_image,
            grayscale=np.zeros(
                (10, 10),
                dtype=np.uint8,
            ),
        )

        with self.assertRaises(
            ECGLeadSignalExtractionError
        ):
            extract_ecg_lead_signals(
                invalid_image,
                identification,
            )

    def test_rejects_invalid_grayscale_dtype(self):
        (
            processed_image,
            identification,
            _,
        ) = self.create_valid_inputs()

        invalid_image = replace(
            processed_image,
            grayscale=np.zeros(
                (36, 80),
                dtype=np.float32,
            ),
        )

        with self.assertRaisesRegex(
            ECGLeadSignalExtractionError,
            "must use uint8 pixels",
        ):
            extract_ecg_lead_signals(
                invalid_image,
                identification,
            )

    # =========================================================
    # 5. Lead Identification Validation
    # =========================================================

    def test_rejects_invalid_identification_input(self):
        processed_image, _ = (
            self.create_processed_image()
        )

        with self.assertRaisesRegex(
            ECGLeadSignalExtractionError,
            "A valid ECGLeadIdentificationResult is required",
        ):
            extract_ecg_lead_signals(
                processed_image,
                "invalid-identification",
            )

    def test_rejects_incomplete_lead_identification(self):
        (
            processed_image,
            identification,
            _,
        ) = self.create_valid_inputs()

        incomplete = replace(
            identification,
            leads=identification.leads[:-1],
        )

        with self.assertRaisesRegex(
            ECGLeadSignalExtractionError,
            "Twelve unique",
        ):
            extract_ecg_lead_signals(
                processed_image,
                incomplete,
            )

    def test_rejects_inconsistent_cell_coordinates(self):
        (
            processed_image,
            identification,
            _,
        ) = self.create_valid_inputs()

        invalid_identification = (
            self.change_identified_lead(
                identification,
                position=0,
                row_index=2,
            )
        )

        with self.assertRaisesRegex(
            ECGLeadSignalExtractionError,
            "inconsistent cell coordinates",
        ):
            extract_ecg_lead_signals(
                processed_image,
                invalid_identification,
            )

    def test_rejects_cell_outside_horizontal_image_bounds(self):
        (
            processed_image,
            identification,
            _,
        ) = self.create_valid_inputs()

        first_lead = identification.leads[0]

        invalid_cell = replace(
            first_lead.cell,
            left=-1,
        )

        invalid_identification = (
            self.change_identified_lead(
                identification,
                position=0,
                cell=invalid_cell,
            )
        )

        with self.assertRaisesRegex(
            ECGLeadSignalExtractionError,
            "invalid horizontal boundaries",
        ):
            extract_ecg_lead_signals(
                processed_image,
                invalid_identification,
            )

    def test_rejects_cell_outside_vertical_image_bounds(self):
        (
            processed_image,
            identification,
            _,
        ) = self.create_valid_inputs()

        first_lead = identification.leads[0]

        invalid_cell = replace(
            first_lead.cell,
            top=-1,
        )

        invalid_identification = (
            self.change_identified_lead(
                identification,
                position=0,
                cell=invalid_cell,
            )
        )

        with self.assertRaisesRegex(
            ECGLeadSignalExtractionError,
            "invalid vertical boundaries",
        ):
            extract_ecg_lead_signals(
                processed_image,
                invalid_identification,
            )

    def test_rejects_overlapping_lead_cells(self):
        (
            processed_image,
            identification,
            _,
        ) = self.create_valid_inputs()

        second_lead = identification.leads[1]

        overlapping_cell = replace(
            second_lead.cell,
            left=10,
            right=30,
        )

        invalid_identification = (
            self.change_identified_lead(
                identification,
                position=1,
                cell=overlapping_cell,
            )
        )

        with self.assertRaisesRegex(
            ECGLeadSignalExtractionError,
            "must not overlap",
        ):
            extract_ecg_lead_signals(
                processed_image,
                invalid_identification,
            )

    # =========================================================
    # 6. Safe Failure Handling
    # =========================================================

    def test_wraps_trace_extraction_failure_safely(self):
        (
            processed_image,
            identification,
            _,
        ) = self.create_valid_inputs()

        with patch(
            "ecg.services.lead_signal_extraction.extract_trace_candidates",
            side_effect=ECGTraceExtractionError(
                "Simulated extraction failure."
            ),
        ):

            with self.assertRaises(
                ECGLeadSignalExtractionError
            ) as context:

                extract_ecg_lead_signals(
                    processed_image,
                    identification,
                )

        self.assertIn(
            "ECG lead I",
            str(context.exception),
        )

        self.assertIsInstance(
            context.exception.__cause__,
            ECGTraceExtractionError,
        )

    def test_wraps_signal_reconstruction_failure_safely(self):
        (
            processed_image,
            identification,
            _,
        ) = self.create_valid_inputs()

        with patch(
            "ecg.services.lead_signal_extraction.reconstruct_ecg_signal",
            side_effect=ECGSignalReconstructionError(
                "Simulated reconstruction failure."
            ),
        ):

            with self.assertRaises(
                ECGLeadSignalExtractionError
            ) as context:

                extract_ecg_lead_signals(
                    processed_image,
                    identification,
                )

        self.assertIn(
            "ECG lead I",
            str(context.exception),
        )

        self.assertIsInstance(
            context.exception.__cause__,
            ECGSignalReconstructionError,
        )
