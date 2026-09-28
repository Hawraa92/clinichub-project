
"""
ECG Lead Identification and Naming Foundation.

This module assigns standard ECG lead names to previously detected
2D layout cells.

Important:
    Lead names must never be inferred from cell positions alone.
    An explicitly selected, supported layout format is required.

This is an engineering/research component.
It does not perform ECG interpretation or clinical diagnosis.
"""

from dataclasses import dataclass

from ecg.services.lead_segmentation import (
    ECGLeadLayoutCell,
    ECGLeadLayoutResult,
)


# ---------------------------------------------------------
# Constants
# ---------------------------------------------------------

STANDARD_ECG_LEAD_NAMES = (
    "I",
    "II",
    "III",
    "aVR",
    "aVL",
    "aVF",
    "V1",
    "V2",
    "V3",
    "V4",
    "V5",
    "V6",
)


# One explicitly supported 3-row x 4-column ECG arrangement.
#
# Other ECG printout formats may use different lead positions.
# Therefore, this template must not be applied automatically
# to every detected 3x4 grid.

STANDARD_3X4_LEAD_LAYOUT = (
    ("I", "aVR", "V1", "V4"),
    ("II", "aVL", "V2", "V5"),
    ("III", "aVF", "V3", "V6"),
)


SUPPORTED_ECG_LEAD_LAYOUTS = {
    "standard_3x4": STANDARD_3X4_LEAD_LAYOUT,
}


# ---------------------------------------------------------
# Exceptions
# ---------------------------------------------------------

class ECGLeadIdentificationError(ValueError):
    """Raised when ECG lead naming cannot be performed safely."""


# ---------------------------------------------------------
# Result models
# ---------------------------------------------------------

@dataclass(frozen=True)
class ECGIdentifiedLead:
    """
    A detected ECG layout cell with an explicitly assigned lead name.

    The cell contains the original spatial information.
    """

    name: str
    row_index: int
    column_index: int
    cell: ECGLeadLayoutCell

    @property
    def index(self) -> int:
        return self.cell.index

    @property
    def left(self) -> int:
        return self.cell.left

    @property
    def right(self) -> int:
        return self.cell.right

    @property
    def top(self) -> int:
        return self.cell.top

    @property
    def bottom(self) -> int:
        return self.cell.bottom


@dataclass(frozen=True)
class ECGLeadIdentificationResult:
    """
    Result of assigning lead names to a supported ECG layout.
    """

    layout_format: str
    leads: tuple[ECGIdentifiedLead, ...]

    @property
    def lead_count(self) -> int:
        return len(self.leads)

    @property
    def lead_names(self) -> tuple[str, ...]:
        return tuple(
            lead.name
            for lead in self.leads
        )

    @property
    def complete_12_lead(self) -> bool:
        return (
            self.lead_count == 12
            and set(self.lead_names) == set(STANDARD_ECG_LEAD_NAMES)
        )

    def get_lead(
        self,
        name: str,
    ) -> ECGIdentifiedLead | None:
        """
        Retrieve an identified lead by its exact standard name.

        Returns None when the lead is not present.
        """

        for lead in self.leads:
            if lead.name == name:
                return lead

        return None


# ---------------------------------------------------------
# Internal validation
# ---------------------------------------------------------

def _get_explicit_layout_template(
    layout_format: str | None,
) -> tuple[tuple[str, ...], ...]:
    """
    Resolve an explicitly requested, supported lead arrangement.
    """

    if layout_format is None:
        raise ECGLeadIdentificationError(
            "An explicit ECG lead layout format is required. "
            "Lead names cannot be inferred safely from "
            "cell positions alone."
        )

    if not isinstance(layout_format, str):
        raise ECGLeadIdentificationError(
            "The ECG lead layout format must be a string."
        )

    template = SUPPORTED_ECG_LEAD_LAYOUTS.get(
        layout_format
    )

    if template is None:
        raise ECGLeadIdentificationError(
            f"Unsupported ECG lead layout format: "
            f"{layout_format!r}."
        )

    return template


def _validate_lead_layout(
    lead_layout: ECGLeadLayoutResult,
    template: tuple[tuple[str, ...], ...],
) -> dict[tuple[int, int], ECGLeadLayoutCell]:
    """
    Validate the detected cell structure against the selected template.

    A mismatch must raise an error rather than produce potentially
    incorrect lead names.
    """

    if not isinstance(
        lead_layout,
        ECGLeadLayoutResult,
    ):
        raise ECGLeadIdentificationError(
            "A valid ECGLeadLayoutResult is required."
        )

    if lead_layout.width <= 0 or lead_layout.height <= 0:
        raise ECGLeadIdentificationError(
            "The ECG layout dimensions must be positive."
        )

    expected_row_count = len(template)

    expected_positions = {
        (row_index, column_index)
        for row_index, row_names in enumerate(
            template,
            start=1,
        )
        for column_index in range(
            1,
            len(row_names) + 1,
        )
    }

    expected_cell_count = len(expected_positions)

    if len(lead_layout.rows) != expected_row_count:
        raise ECGLeadIdentificationError(
            "The detected ECG row count does not match "
            "the selected lead layout format."
        )

    row_indices = [
        row.index
        for row in lead_layout.rows
    ]

    if (
        len(set(row_indices)) != expected_row_count
        or set(row_indices) != set(
            range(1, expected_row_count + 1)
        )
    ):
        raise ECGLeadIdentificationError(
            "The ECG layout contains invalid or duplicate "
            "row indices."
        )

    if len(lead_layout.cells) != expected_cell_count:
        raise ECGLeadIdentificationError(
            "The detected ECG cell count does not match "
            "the selected lead layout format."
        )

    cells_by_position = {}
    seen_cell_indices = set()

    for cell in lead_layout.cells:

        if not isinstance(cell, ECGLeadLayoutCell):
            raise ECGLeadIdentificationError(
                "The ECG layout contains an invalid cell."
            )

        position = (
            cell.row_index,
            cell.column_index,
        )

        if position not in expected_positions:
            raise ECGLeadIdentificationError(
                "The ECG layout contains a cell outside "
                "the expected row and column positions."
            )

        if position in cells_by_position:
            raise ECGLeadIdentificationError(
                "Duplicate ECG layout cell position detected."
            )

        if (
            cell.index <= 0
            or cell.index in seen_cell_indices
        ):
            raise ECGLeadIdentificationError(
                "The ECG layout contains an invalid "
                "or duplicate cell index."
            )

        if not (
            0 <= cell.left < cell.right <= lead_layout.width
        ):
            raise ECGLeadIdentificationError(
                "Invalid horizontal ECG cell boundaries."
            )

        if not (
            0 <= cell.top < cell.bottom <= lead_layout.height
        ):
            raise ECGLeadIdentificationError(
                "Invalid vertical ECG cell boundaries."
            )

        cells_by_position[position] = cell
        seen_cell_indices.add(cell.index)

    if set(cells_by_position) != expected_positions:
        raise ECGLeadIdentificationError(
            "The detected ECG layout is incomplete."
        )

    return cells_by_position


# ---------------------------------------------------------
# Public identification function
# ---------------------------------------------------------

def identify_ecg_leads(
    lead_layout: ECGLeadLayoutResult,
    *,
    layout_format: str | None = None,
) -> ECGLeadIdentificationResult:
    """
    Assign standard lead names to detected ECG layout cells.

    Parameters
    ----------
    lead_layout:
        The result of the previous 2D ECG layout segmentation stage.

    layout_format:
        The explicitly selected ECG arrangement.

        Currently supported:
            "standard_3x4"

        No format is selected automatically.

    Returns
    -------
    ECGLeadIdentificationResult:
        Twelve named lead-cell associations in row-major order.

    Raises
    ------
    ECGLeadIdentificationError:
        If the layout format is missing, unsupported, malformed,
        incomplete, or incompatible with the detected cells.

    Notes
    -----
    Naming a cell does not guarantee successful extraction of
    the ECG trace inside it.

    Signal extraction and signal quality verification are
    separate processing stages.
    """

    template = _get_explicit_layout_template(
        layout_format
    )

    cells_by_position = _validate_lead_layout(
        lead_layout,
        template,
    )

    identified_leads = []

    for row_index, row_names in enumerate(
        template,
        start=1,
    ):
        for column_index, lead_name in enumerate(
            row_names,
            start=1,
        ):

            position = (
                row_index,
                column_index,
            )

            cell = cells_by_position[position]

            identified_leads.append(
                ECGIdentifiedLead(
                    name=lead_name,
                    row_index=row_index,
                    column_index=column_index,
                    cell=cell,
                )
            )

    result = ECGLeadIdentificationResult(
        layout_format=layout_format,
        leads=tuple(identified_leads),
    )

    if not result.complete_12_lead:
        raise ECGLeadIdentificationError(
            "The identified layout does not contain "
            "twelve unique standard ECG leads."
        )

    return result
