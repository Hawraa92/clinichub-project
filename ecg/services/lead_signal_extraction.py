
"""
ECG Per-Lead Signal Extraction Foundation.

Extract a separate digital ECG trace from each previously identified
ECG layout cell.

Each cell is cropped using both horizontal and vertical boundaries
before trace extraction and signal reconstruction.

Important:
    Lead names must already have been assigned using an explicitly
    selected layout format.

    This module performs image/signal processing only. It does not
    interpret ECG morphology or provide a clinical diagnosis.
"""

from dataclasses import dataclass

import numpy as np

from ecg.services.image_processing import (
    ProcessedECGImage,
)
from ecg.services.lead_identification import (
    ECGIdentifiedLead,
    ECGLeadIdentificationResult,
    STANDARD_ECG_LEAD_NAMES,
)
from ecg.services.lead_segmentation import (
    ECGLeadLayoutCell,
)
from ecg.services.signal_reconstruction import (
    ECGSignalReconstructionError,
    ReconstructedECGSignal,
    reconstruct_ecg_signal,
)
from ecg.services.trace_extraction import (
    ECGTraceExtractionError,
    extract_trace_candidates,
)


# =========================================================
# Exceptions
# =========================================================

class ECGLeadSignalExtractionError(ValueError):
    """
    Raised when independent lead extraction cannot complete safely.
    """


# =========================================================
# Result Models
# =========================================================

@dataclass(frozen=True)
class ECGExtractedLeadSignal:
    """
    A reconstructed signal belonging to one identified ECG cell.

    The reconstructed signal uses local cell coordinates.

    image_left and image_top allow coordinates to be mapped back
    to the original processed ECG image.
    """

    name: str
    row_index: int
    column_index: int
    cell: ECGLeadLayoutCell
    reconstructed_signal: ReconstructedECGSignal

    image_left: int
    image_top: int

    @property
    def sample_count(self) -> int:
        return self.reconstructed_signal.sample_count

    @property
    def missing_count(self) -> int:
        return self.reconstructed_signal.missing_count

    @property
    def coverage_ratio(self) -> float:
        return self.reconstructed_signal.coverage_ratio

    @property
    def signal_values(self):
        return self.reconstructed_signal.signal_values

    @property
    def x_positions_local(self):
        return self.reconstructed_signal.x_positions

    @property
    def x_positions_global(self):
        """
        Convert local horizontal positions to original image positions.
        """

        return tuple(
            x_position + self.image_left
            for x_position in self.reconstructed_signal.x_positions
        )

    @property
    def y_positions_global(self):
        """
        Convert local vertical positions to original image positions.

        Missing samples remain None.
        """

        return tuple(
            (
                None
                if y_position is None
                else y_position + self.image_top
            )
            for y_position in self.reconstructed_signal.y_positions
        )


@dataclass(frozen=True)
class ECGLeadSignalExtractionResult:
    """
    Collection of independently reconstructed, named ECG signals.
    """

    layout_format: str
    source_width: int
    source_height: int

    leads: tuple[ECGExtractedLeadSignal, ...]

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
            and len(set(self.lead_names)) == 12
            and set(self.lead_names) == set(
                STANDARD_ECG_LEAD_NAMES
            )
        )

    def get_lead(
        self,
        name: str,
    ) -> ECGExtractedLeadSignal | None:
        """
        Retrieve an independently reconstructed lead by name.
        """

        for lead in self.leads:
            if lead.name == name:
                return lead

        return None

    @property
    def coverage_by_lead(self) -> dict[str, float]:
        """
        Expose the reconstruction coverage for each individual lead.
        """

        return {
            lead.name: lead.coverage_ratio
            for lead in self.leads
        }


# =========================================================
# Image Validation
# =========================================================

def _validate_processed_image(
    processed_image: ProcessedECGImage,
) -> np.ndarray:
    """
    Validate the processed grayscale ECG image.

    Return its pixel data as a two-dimensional NumPy array.
    """

    if not isinstance(
        processed_image,
        ProcessedECGImage,
    ):
        raise ECGLeadSignalExtractionError(
            "A valid ProcessedECGImage is required."
        )

    width = processed_image.width
    height = processed_image.height

    if width <= 0 or height <= 0:
        raise ECGLeadSignalExtractionError(
            "The processed ECG image dimensions must be positive."
        )

    grayscale = np.asarray(
        processed_image.grayscale
    )

    if grayscale.ndim == 1:
        if grayscale.size != width * height:
            raise ECGLeadSignalExtractionError(
                "The ECG grayscale data size does not match "
                "the image dimensions."
            )

        grayscale = grayscale.reshape(
            height,
            width,
        )

    if (
        grayscale.ndim != 2
        or grayscale.shape != (height, width)
    ):
        raise ECGLeadSignalExtractionError(
            "The ECG grayscale image has an invalid shape."
        )

    if grayscale.dtype != np.uint8:
        raise ECGLeadSignalExtractionError(
            "The processed ECG grayscale data must use uint8 pixels."
        )

    return np.ascontiguousarray(
        grayscale
    )


# =========================================================
# Lead Identification Validation
# =========================================================

def _validate_identified_leads(
    lead_identification: ECGLeadIdentificationResult,
    *,
    image_width: int,
    image_height: int,
) -> tuple[ECGIdentifiedLead, ...]:
    """
    Validate identified lead cells before reconstructing signals.
    """

    if not isinstance(
        lead_identification,
        ECGLeadIdentificationResult,
    ):
        raise ECGLeadSignalExtractionError(
            "A valid ECGLeadIdentificationResult is required."
        )

    if not lead_identification.complete_12_lead:
        raise ECGLeadSignalExtractionError(
            "Twelve unique, explicitly identified ECG leads "
            "are required for this extraction stage."
        )

    identified_leads = lead_identification.leads

    seen_positions = set()
    seen_names = set()

    for lead in identified_leads:

        if not isinstance(
            lead,
            ECGIdentifiedLead,
        ):
            raise ECGLeadSignalExtractionError(
                "The identification result contains an invalid lead."
            )

        cell = lead.cell

        if not isinstance(
            cell,
            ECGLeadLayoutCell,
        ):
            raise ECGLeadSignalExtractionError(
                f"Lead {lead.name} contains an invalid layout cell."
            )

        position = (
            lead.row_index,
            lead.column_index,
        )

        if position in seen_positions:
            raise ECGLeadSignalExtractionError(
                "Duplicate identified ECG cell position detected."
            )

        if lead.name in seen_names:
            raise ECGLeadSignalExtractionError(
                "Duplicate identified ECG lead name detected."
            )

        if (
            cell.row_index != lead.row_index
            or cell.column_index != lead.column_index
        ):
            raise ECGLeadSignalExtractionError(
                f"Lead {lead.name} has inconsistent cell coordinates."
            )

        if not (
            0 <= cell.left < cell.right <= image_width
        ):
            raise ECGLeadSignalExtractionError(
                f"Lead {lead.name} has invalid horizontal boundaries."
            )

        if not (
            0 <= cell.top < cell.bottom <= image_height
        ):
            raise ECGLeadSignalExtractionError(
                f"Lead {lead.name} has invalid vertical boundaries."
            )

        seen_positions.add(position)
        seen_names.add(lead.name)

    # Ensure that two identified leads do not share image pixels.
    # Adjacent cells may touch at their boundaries.

    for first_index, first_lead in enumerate(
        identified_leads
    ):
        first_cell = first_lead.cell

        for second_lead in identified_leads[
            first_index + 1:
        ]:
            second_cell = second_lead.cell

            horizontal_overlap = (
                first_cell.left < second_cell.right
                and second_cell.left < first_cell.right
            )

            vertical_overlap = (
                first_cell.top < second_cell.bottom
                and second_cell.top < first_cell.bottom
            )

            if horizontal_overlap and vertical_overlap:
                raise ECGLeadSignalExtractionError(
                    "Identified ECG lead cells must not overlap."
                )

    return identified_leads


# =========================================================
# Independent Cell Cropping
# =========================================================

def _crop_identified_lead_image(
    processed_image: ProcessedECGImage,
    grayscale: np.ndarray,
    lead: ECGIdentifiedLead,
) -> ProcessedECGImage:
    """
    Produce an independent grayscale image for one ECG cell.

    Both X and Y boundaries are applied before reconstruction.
    """

    cell = lead.cell

    left = cell.left
    right = cell.right

    top = cell.top
    bottom = cell.bottom

    cropped_grayscale = np.array(
        grayscale[top:bottom, left:right],
        dtype=np.uint8,
        copy=True,
        order="C",
    )

    cropped_height, cropped_width = (
        cropped_grayscale.shape
    )

    if cropped_width <= 0 or cropped_height <= 0:
        raise ECGLeadSignalExtractionError(
            f"Lead {lead.name} produced an empty image crop."
        )

    return ProcessedECGImage(
        width=cropped_width,
        height=cropped_height,
        source_mode=processed_image.source_mode,
        grayscale=cropped_grayscale,
    )


# =========================================================
# Independent Signal Reconstruction
# =========================================================

def _reconstruct_identified_lead(
    processed_image: ProcessedECGImage,
    grayscale: np.ndarray,
    lead: ECGIdentifiedLead,
) -> ECGExtractedLeadSignal:
    """
    Extract and reconstruct the trace inside one isolated lead cell.
    """

    cropped_image = _crop_identified_lead_image(
        processed_image,
        grayscale,
        lead,
    )

    try:
        cropped_candidates = extract_trace_candidates(
            cropped_image
        )
    except ECGTraceExtractionError as exc:
        raise ECGLeadSignalExtractionError(
            f"Trace candidates could not be extracted "
            f"safely for ECG lead {lead.name}."
        ) from exc

    try:
        reconstructed_signal = reconstruct_ecg_signal(
            cropped_candidates,
            region_top=0,
            region_bottom=cropped_image.height,
        )
    except ECGSignalReconstructionError as exc:
        raise ECGLeadSignalExtractionError(
            f"The digital signal for ECG lead {lead.name} "
            "could not be reconstructed safely."
        ) from exc

    return ECGExtractedLeadSignal(
        name=lead.name,
        row_index=lead.row_index,
        column_index=lead.column_index,
        cell=lead.cell,
        reconstructed_signal=reconstructed_signal,
        image_left=lead.cell.left,
        image_top=lead.cell.top,
    )


# =========================================================
# Public Service
# =========================================================

def extract_ecg_lead_signals(
    processed_image: ProcessedECGImage,
    lead_identification: ECGLeadIdentificationResult,
) -> ECGLeadSignalExtractionResult:
    """
    Extract twelve independent digital ECG signals.

    Parameters
    ----------
    processed_image:
        The processed ECG image. Perspective correction, when
        requested, must already have been applied.

    lead_identification:
        An explicitly named and validated ECG lead layout.

    Returns
    -------
    ECGLeadSignalExtractionResult:
        The individually reconstructed signals, associated with
        their lead names and source-image coordinates.

    Raises
    ------
    ECGLeadSignalExtractionError:
        If image validation, cell validation, trace extraction,
        or reconstruction fails.

    Notes
    -----
    The function does not return a misleading complete result
    when one of the required leads cannot be reconstructed.

    Calibration, per-lead quality assessment, clinical validation,
    and ECG interpretation are separate responsibilities.
    """

    grayscale = _validate_processed_image(
        processed_image
    )

    identified_leads = _validate_identified_leads(
        lead_identification,
        image_width=processed_image.width,
        image_height=processed_image.height,
    )

    extracted_leads = []

    for lead in identified_leads:

        extracted_lead = _reconstruct_identified_lead(
            processed_image,
            grayscale,
            lead,
        )

        extracted_leads.append(
            extracted_lead
        )

    result = ECGLeadSignalExtractionResult(
        layout_format=lead_identification.layout_format,
        source_width=processed_image.width,
        source_height=processed_image.height,
        leads=tuple(extracted_leads),
    )

    if not result.complete_12_lead:
        raise ECGLeadSignalExtractionError(
            "Independent ECG extraction did not produce "
            "twelve unique named lead signals."
        )

    return result
