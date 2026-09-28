
"""
Tests for ECG Lead Identification and Naming Foundation.

These tests verify that:

1. Standard ECG lead names are assigned correctly.
2. Explicit layout selection is required.
3. Cell ordering does not affect lead identification.
4. Original spatial information is preserved.
5. Incomplete or malformed layouts are rejected.
6. Duplicate cell positions and indices are rejected.

No clinical ECG interpretation is performed here.
"""

from dataclasses import replace

from django.test import SimpleTestCase

from ecg.services.lead_identification import (
    ECGIdentifiedLead,
    ECGLeadIdentificationError,
    ECGLeadIdentificationResult,
    STANDARD_ECG_LEAD_NAMES,
    STANDARD_3X4_LEAD_LAYOUT,
    SUPPORTED_ECG_LEAD_LAYOUTS,
    identify_ecg_leads,
)

from ecg.services.lead_segmentation import (
    ECGLeadLayoutCell,
    ECGLeadLayoutResult,
    ECGLeadRegion,
)


class ECGLeadIdentificationTests(SimpleTestCase):

    # =========================================================
    # Test Fixtures
    # =========================================================

    def create_layout(self):
        """
        Create a synthetic 3-row x 4-column ECG layout.

        The layout contains exactly twelve cells.
        """

        rows = (
            ECGLeadRegion(
                index=1,
                top=0,
                bottom=4,
                active_top=1,
                active_bottom=3,
                candidate_pixel_count=20,
            ),
            ECGLeadRegion(
                index=2,
                top=4,
                bottom=8,
                active_top=5,
                active_bottom=7,
                candidate_pixel_count=20,
            ),
            ECGLeadRegion(
                index=3,
                top=8,
                bottom=12,
                active_top=9,
                active_bottom=11,
                candidate_pixel_count=20,
            ),
        )

        cells = []
        cell_index = 1

        for row in rows:
            for column_index in range(1, 5):

                left = (column_index - 1) * 5
                right = column_index * 5

                cells.append(
                    ECGLeadLayoutCell(
                        index=cell_index,
                        row_index=row.index,
                        column_index=column_index,
                        left=left,
                        right=right,
                        top=row.top,
                        bottom=row.bottom,
                        active_left=left,
                        active_right=right,
                        active_top=row.active_top,
                        active_bottom=row.active_bottom,
                        candidate_pixel_count=5,
                    )
                )

                cell_index += 1

        return ECGLeadLayoutResult(
            width=20,
            height=12,
            rows=rows,
            cells=tuple(cells),
        )

    def change_cell(
        self,
        layout,
        cell_position,
        **changes,
    ):
        """
        Return a modified layout without modifying the original.
        """

        cells = list(layout.cells)

        cells[cell_position] = replace(
            cells[cell_position],
            **changes,
        )

        return replace(
            layout,
            cells=tuple(cells),
        )

    def change_row(
        self,
        layout,
        row_position,
        **changes,
    ):
        """
        Return a layout with one modified row.
        """

        rows = list(layout.rows)

        rows[row_position] = replace(
            rows[row_position],
            **changes,
        )

        return replace(
            layout,
            rows=tuple(rows),
        )

    # =========================================================
    # 1. Standard Lead Naming
    # =========================================================

    def test_standard_3x4_template_contains_expected_leads(self):
        self.assertEqual(
            STANDARD_3X4_LEAD_LAYOUT,
            (
                ("I", "aVR", "V1", "V4"),
                ("II", "aVL", "V2", "V5"),
                ("III", "aVF", "V3", "V6"),
            ),
        )

        flattened_names = tuple(
            name
            for row in STANDARD_3X4_LEAD_LAYOUT
            for name in row
        )

        self.assertEqual(len(flattened_names), 12)

        self.assertEqual(
            set(flattened_names),
            set(STANDARD_ECG_LEAD_NAMES),
        )

    def test_standard_3x4_format_is_registered(self):
        self.assertIn(
            "standard_3x4",
            SUPPORTED_ECG_LEAD_LAYOUTS,
        )

        self.assertEqual(
            SUPPORTED_ECG_LEAD_LAYOUTS["standard_3x4"],
            STANDARD_3X4_LEAD_LAYOUT,
        )

    def test_identifies_all_twelve_standard_ecg_leads(self):
        layout = self.create_layout()

        result = identify_ecg_leads(
            layout,
            layout_format="standard_3x4",
        )

        self.assertIsInstance(
            result,
            ECGLeadIdentificationResult,
        )

        self.assertEqual(
            result.layout_format,
            "standard_3x4",
        )

        self.assertEqual(result.lead_count, 12)

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

        self.assertTrue(result.complete_12_lead)

    def test_every_identified_lead_has_correct_row_and_column(self):
        layout = self.create_layout()

        result = identify_ecg_leads(
            layout,
            layout_format="standard_3x4",
        )

        expected_positions = {
            "I": (1, 1),
            "aVR": (1, 2),
            "V1": (1, 3),
            "V4": (1, 4),
            "II": (2, 1),
            "aVL": (2, 2),
            "V2": (2, 3),
            "V5": (2, 4),
            "III": (3, 1),
            "aVF": (3, 2),
            "V3": (3, 3),
            "V6": (3, 4),
        }

        for lead_name, expected_position in expected_positions.items():

            with self.subTest(lead=lead_name):

                lead = result.get_lead(lead_name)

                self.assertIsNotNone(lead)

                self.assertIsInstance(
                    lead,
                    ECGIdentifiedLead,
                )

                self.assertEqual(
                    (
                        lead.row_index,
                        lead.column_index,
                    ),
                    expected_position,
                )

    def test_identification_is_independent_of_input_cell_order(self):
        layout = self.create_layout()

        shuffled_layout = replace(
            layout,
            cells=tuple(reversed(layout.cells)),
        )

        result = identify_ecg_leads(
            shuffled_layout,
            layout_format="standard_3x4",
        )

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

        self.assertTrue(result.complete_12_lead)

    def test_identification_preserves_original_cell_objects(self):
        layout = self.create_layout()

        result = identify_ecg_leads(
            layout,
            layout_format="standard_3x4",
        )

        cells_by_position = {
            (cell.row_index, cell.column_index): cell
            for cell in layout.cells
        }

        for lead in result.leads:

            with self.subTest(lead=lead.name):

                original_cell = cells_by_position[
                    (lead.row_index, lead.column_index)
                ]

                self.assertIs(
                    lead.cell,
                    original_cell,
                )

                self.assertEqual(
                    lead.index,
                    original_cell.index,
                )

    def test_identified_lead_exposes_original_cell_boundaries(self):
        layout = self.create_layout()

        result = identify_ecg_leads(
            layout,
            layout_format="standard_3x4",
        )

        lead = result.get_lead("I")

        self.assertIsNotNone(lead)

        self.assertEqual(lead.left, 0)
        self.assertEqual(lead.right, 5)

        self.assertEqual(lead.top, 0)
        self.assertEqual(lead.bottom, 4)

        self.assertEqual(lead.index, 1)

    # =========================================================
    # 2. Lead Result Access
    # =========================================================

    def test_get_lead_returns_correct_named_lead(self):
        layout = self.create_layout()

        result = identify_ecg_leads(
            layout,
            layout_format="standard_3x4",
        )

        lead_i = result.get_lead("I")
        lead_v6 = result.get_lead("V6")

        self.assertIsNotNone(lead_i)
        self.assertIsNotNone(lead_v6)

        self.assertEqual(lead_i.name, "I")
        self.assertEqual(lead_v6.name, "V6")

        self.assertEqual(
            (lead_i.row_index, lead_i.column_index),
            (1, 1),
        )

        self.assertEqual(
            (lead_v6.row_index, lead_v6.column_index),
            (3, 4),
        )

    def test_get_lead_returns_none_for_unknown_name(self):
        layout = self.create_layout()

        result = identify_ecg_leads(
            layout,
            layout_format="standard_3x4",
        )

        self.assertIsNone(
            result.get_lead("UNKNOWN")
        )

        self.assertIsNone(
            result.get_lead("V7")
        )

    def test_get_lead_uses_exact_standard_name(self):
        layout = self.create_layout()

        result = identify_ecg_leads(
            layout,
            layout_format="standard_3x4",
        )

        self.assertIsNotNone(
            result.get_lead("aVR")
        )

        self.assertIsNone(
            result.get_lead("avr")
        )

    # =========================================================
    # 3. Explicit Format Requirement
    # =========================================================

    def test_rejects_missing_explicit_layout_format(self):
        layout = self.create_layout()

        with self.assertRaisesRegex(
            ECGLeadIdentificationError,
            "explicit ECG lead layout format is required",
        ):
            identify_ecg_leads(layout)

    def test_rejects_empty_layout_format(self):
        layout = self.create_layout()

        with self.assertRaisesRegex(
            ECGLeadIdentificationError,
            "Unsupported ECG lead layout format",
        ):
            identify_ecg_leads(
                layout,
                layout_format="",
            )

    def test_rejects_unknown_layout_format(self):
        layout = self.create_layout()

        with self.assertRaisesRegex(
            ECGLeadIdentificationError,
            "Unsupported ECG lead layout format",
        ):
            identify_ecg_leads(
                layout,
                layout_format="unknown_format",
            )

    def test_rejects_non_string_layout_format(self):
        layout = self.create_layout()

        invalid_formats = (
            123,
            True,
            [],
            {},
        )

        for invalid_format in invalid_formats:

            with self.subTest(value=invalid_format):

                with self.assertRaisesRegex(
                    ECGLeadIdentificationError,
                    "must be a string",
                ):
                    identify_ecg_leads(
                        layout,
                        layout_format=invalid_format,
                    )

    def test_rejects_invalid_layout_input_type(self):
        with self.assertRaisesRegex(
            ECGLeadIdentificationError,
            "A valid ECGLeadLayoutResult is required",
        ):
            identify_ecg_leads(
                "not-a-layout",
                layout_format="standard_3x4",
            )

    # =========================================================
    # 4. Layout Dimensions and Row Validation
    # =========================================================

    def test_rejects_non_positive_layout_width(self):
        layout = self.create_layout()

        invalid_layout = replace(
            layout,
            width=0,
        )

        with self.assertRaisesRegex(
            ECGLeadIdentificationError,
            "dimensions must be positive",
        ):
            identify_ecg_leads(
                invalid_layout,
                layout_format="standard_3x4",
            )

    def test_rejects_non_positive_layout_height(self):
        layout = self.create_layout()

        invalid_layout = replace(
            layout,
            height=0,
        )

        with self.assertRaisesRegex(
            ECGLeadIdentificationError,
            "dimensions must be positive",
        ):
            identify_ecg_leads(
                invalid_layout,
                layout_format="standard_3x4",
            )

    def test_rejects_incorrect_row_count(self):
        layout = self.create_layout()

        invalid_layout = replace(
            layout,
            rows=layout.rows[:2],
        )

        with self.assertRaisesRegex(
            ECGLeadIdentificationError,
            "row count does not match",
        ):
            identify_ecg_leads(
                invalid_layout,
                layout_format="standard_3x4",
            )

    def test_rejects_duplicate_row_indices(self):
        layout = self.create_layout()

        invalid_layout = self.change_row(
            layout,
            row_position=1,
            index=1,
        )

        with self.assertRaisesRegex(
            ECGLeadIdentificationError,
            "invalid or duplicate row indices",
        ):
            identify_ecg_leads(
                invalid_layout,
                layout_format="standard_3x4",
            )

    def test_rejects_unexpected_row_index(self):
        layout = self.create_layout()

        invalid_layout = self.change_row(
            layout,
            row_position=2,
            index=4,
        )

        with self.assertRaisesRegex(
            ECGLeadIdentificationError,
            "invalid or duplicate row indices",
        ):
            identify_ecg_leads(
                invalid_layout,
                layout_format="standard_3x4",
            )

    # =========================================================
    # 5. Cell Count and Cell Structure Validation
    # =========================================================

    def test_rejects_missing_layout_cell(self):
        layout = self.create_layout()

        invalid_layout = replace(
            layout,
            cells=layout.cells[:-1],
        )

        with self.assertRaisesRegex(
            ECGLeadIdentificationError,
            "cell count does not match",
        ):
            identify_ecg_leads(
                invalid_layout,
                layout_format="standard_3x4",
            )

    def test_rejects_extra_layout_cell(self):
        layout = self.create_layout()

        invalid_layout = replace(
            layout,
            cells=layout.cells + (layout.cells[0],),
        )

        with self.assertRaisesRegex(
            ECGLeadIdentificationError,
            "cell count does not match",
        ):
            identify_ecg_leads(
                invalid_layout,
                layout_format="standard_3x4",
            )

    def test_rejects_invalid_cell_object(self):
        layout = self.create_layout()

        cells = list(layout.cells)
        cells[0] = object()

        invalid_layout = replace(
            layout,
            cells=tuple(cells),
        )

        with self.assertRaisesRegex(
            ECGLeadIdentificationError,
            "contains an invalid cell",
        ):
            identify_ecg_leads(
                invalid_layout,
                layout_format="standard_3x4",
            )

    def test_rejects_duplicate_cell_position(self):
        layout = self.create_layout()

        # Cell 2 is changed to the position of cell 1.
        invalid_layout = self.change_cell(
            layout,
            cell_position=1,
            row_index=1,
            column_index=1,
        )

        with self.assertRaisesRegex(
            ECGLeadIdentificationError,
            "Duplicate ECG layout cell position",
        ):
            identify_ecg_leads(
                invalid_layout,
                layout_format="standard_3x4",
            )

    def test_rejects_cell_with_unexpected_column(self):
        layout = self.create_layout()

        invalid_layout = self.change_cell(
            layout,
            cell_position=0,
            column_index=5,
        )

        with self.assertRaisesRegex(
            ECGLeadIdentificationError,
            "outside the expected row and column positions",
        ):
            identify_ecg_leads(
                invalid_layout,
                layout_format="standard_3x4",
            )

    def test_rejects_cell_with_unexpected_row(self):
        layout = self.create_layout()

        invalid_layout = self.change_cell(
            layout,
            cell_position=0,
            row_index=4,
        )

        with self.assertRaisesRegex(
            ECGLeadIdentificationError,
            "outside the expected row and column positions",
        ):
            identify_ecg_leads(
                invalid_layout,
                layout_format="standard_3x4",
            )

    def test_rejects_duplicate_cell_indices(self):
        layout = self.create_layout()

        invalid_layout = self.change_cell(
            layout,
            cell_position=1,
            index=1,
        )

        with self.assertRaisesRegex(
            ECGLeadIdentificationError,
            "invalid or duplicate cell index",
        ):
            identify_ecg_leads(
                invalid_layout,
                layout_format="standard_3x4",
            )

    def test_rejects_non_positive_cell_index(self):
        layout = self.create_layout()

        invalid_layout = self.change_cell(
            layout,
            cell_position=0,
            index=0,
        )

        with self.assertRaisesRegex(
            ECGLeadIdentificationError,
            "invalid or duplicate cell index",
        ):
            identify_ecg_leads(
                invalid_layout,
                layout_format="standard_3x4",
            )

    # =========================================================
    # 6. Cell Boundary Validation
    # =========================================================

    def test_rejects_invalid_horizontal_cell_boundaries(self):
        layout = self.create_layout()

        invalid_cases = (
            {"left": -1},
            {"right": 21},
            {"left": 5, "right": 5},
            {"left": 6, "right": 5},
        )

        for changes in invalid_cases:

            with self.subTest(changes=changes):

                invalid_layout = self.change_cell(
                    layout,
                    cell_position=0,
                    **changes,
                )

                with self.assertRaisesRegex(
                    ECGLeadIdentificationError,
                    "Invalid horizontal ECG cell boundaries",
                ):
                    identify_ecg_leads(
                        invalid_layout,
                        layout_format="standard_3x4",
                    )

    def test_rejects_invalid_vertical_cell_boundaries(self):
        layout = self.create_layout()

        invalid_cases = (
            {"top": -1},
            {"bottom": 13},
            {"top": 4, "bottom": 4},
            {"top": 5, "bottom": 4},
        )

        for changes in invalid_cases:

            with self.subTest(changes=changes):

                invalid_layout = self.change_cell(
                    layout,
                    cell_position=0,
                    **changes,
                )

                with self.assertRaisesRegex(
                    ECGLeadIdentificationError,
                    "Invalid vertical ECG cell boundaries",
                ):
                    identify_ecg_leads(
                        invalid_layout,
                        layout_format="standard_3x4",
                    )
