
from dataclasses import dataclass, replace

from ecg.services.calibration import (
    CalibratedECGSignal,
    ECGCalibrationError,
    calibrate_reconstructed_signal,
)
from ecg.services.grid_detection import (
    ECGGridDetectionError,
    ECGGridDetectionResult,
    detect_ecg_grid_scale,
)
from ecg.services.image_processing import (
    ECGImageProcessingError,
    ProcessedECGImage,
    process_ecg_image,
)
from ecg.services.lead_identification import (
    ECGLeadIdentificationError,
    ECGLeadIdentificationResult,
    identify_ecg_leads,
)
from ecg.services.lead_signal_extraction import (
    ECGLeadSignalExtractionError,
    ECGLeadSignalExtractionResult,
    extract_ecg_lead_signals,
)
from ecg.services.lead_segmentation import (
    ECGLeadLayoutResult,
    ECGLeadRegion,
    ECGLeadSegmentationError,
    ECGLeadSegmentationResult,
    segment_ecg_lead_layout,
    segment_ecg_lead_regions,
)
from ecg.services.paper_detection import (
    ECGPaperDetectionError,
    ECGPaperDetectionResult,
    detect_ecg_paper_corners,
)
from ecg.services.perspective import (
    ECGImageQuadrilateral,
    ECGPerspectiveCorrectionError,
    RectifiedECGImage,
    correct_ecg_perspective,
)
from ecg.services.quality_assessment import (
    ECGQualityAssessmentError,
    ECGQualityAssessmentResult,
    assess_ecg_processing_quality,
)
from ecg.services.signal_reconstruction import (
    ECGSignalReconstructionError,
    ReconstructedECGSignal,
    reconstruct_ecg_signal,
)
from ecg.services.trace_extraction import (
    ECGTraceCandidates,
    ECGTraceExtractionError,
    extract_trace_candidates,
)


# =========================================================
# Pipeline Exception
# =========================================================

class ECGImagePipelineError(ValueError):
    """Raised when the ECG image pipeline cannot complete safely."""


# =========================================================
# Existing Vertical Lead-Region Signal Model
# =========================================================

@dataclass(frozen=True)
class ECGImageLeadSignal:
    region: ECGLeadRegion
    reconstructed_signal: ReconstructedECGSignal
    calibrated_signal: CalibratedECGSignal | None = None

    @property
    def index(self):
        return self.region.index

    @property
    def coverage_ratio(self):
        return self.reconstructed_signal.coverage_ratio

    @property
    def signal_values(self):
        return self.reconstructed_signal.signal_values

    @property
    def x_positions(self):
        return self.reconstructed_signal.x_positions

    @property
    def calibrated(self):
        return self.calibrated_signal is not None


# =========================================================
# Complete Pipeline Result
# =========================================================

@dataclass
class ECGImagePipelineResult:
    processed_image: ProcessedECGImage
    trace_candidates: ECGTraceCandidates
    lead_segmentation: ECGLeadSegmentationResult
    lead_signals: tuple[ECGImageLeadSignal, ...]
    reconstructed_signal: ReconstructedECGSignal

    lead_layout: ECGLeadLayoutResult | None = None
    perspective_correction: RectifiedECGImage | None = None
    paper_detection: ECGPaperDetectionResult | None = None
    grid_detection: ECGGridDetectionResult | None = None
    calibrated_signal: CalibratedECGSignal | None = None

    quality_assessment: ECGQualityAssessmentResult | None = None
    lead_identification: ECGLeadIdentificationResult | None = None

    # NEW: independently reconstructed, named ECG cell signals.
    lead_signal_extraction: ECGLeadSignalExtractionResult | None = None

    @property
    def width(self):
        return self.processed_image.width

    @property
    def height(self):
        return self.processed_image.height

    @property
    def region_count(self):
        return self.lead_segmentation.region_count

    @property
    def reconstructed_signals(self):
        return tuple(
            lead_signal.reconstructed_signal
            for lead_signal in self.lead_signals
        )

    @property
    def coverage_ratio(self):
        return self.reconstructed_signal.coverage_ratio

    @property
    def signal_values(self):
        return self.reconstructed_signal.signal_values

    @property
    def x_positions(self):
        return self.reconstructed_signal.x_positions

    @property
    def perspective_corrected(self):
        return self.perspective_correction is not None

    @property
    def paper_detected(self):
        return self.paper_detection is not None

    @property
    def calibrated(self):
        return self.calibrated_signal is not None

    @property
    def pixels_per_mm(self):
        if self.grid_detection is None:
            return None

        return self.grid_detection.pixels_per_mm

    # ---------------------------------------------------------
    # 2D Layout Properties
    # ---------------------------------------------------------

    @property
    def layout_detected(self):
        return self.lead_layout is not None

    @property
    def layout_row_count(self):
        if self.lead_layout is None:
            return 0

        return self.lead_layout.row_count

    @property
    def layout_cell_count(self):
        if self.lead_layout is None:
            return 0

        return self.lead_layout.cell_count

    @property
    def layout_columns_per_row(self):
        if self.lead_layout is None:
            return ()

        return self.lead_layout.columns_per_row

    # ---------------------------------------------------------
    # Quality Assessment Properties
    # ---------------------------------------------------------

    @property
    def quality_assessed(self):
        return self.quality_assessment is not None

    @property
    def processing_usable(self):
        if self.quality_assessment is None:
            return None

        return self.quality_assessment.usable

    @property
    def processing_quality_level(self):
        if self.quality_assessment is None:
            return None

        return self.quality_assessment.quality_level

    # ---------------------------------------------------------
    # Lead Identification Properties
    # ---------------------------------------------------------

    @property
    def leads_identified(self):
        return self.lead_identification is not None

    @property
    def identified_lead_count(self):
        if self.lead_identification is None:
            return 0

        return self.lead_identification.lead_count

    @property
    def identified_lead_names(self):
        if self.lead_identification is None:
            return ()

        return self.lead_identification.lead_names

    # ---------------------------------------------------------
    # NEW: Independent Per-Lead Extraction Properties
    # ---------------------------------------------------------

    @property
    def per_lead_extracted(self):
        """
        Whether independent extraction was successfully completed.
        """
        return self.lead_signal_extraction is not None

    @property
    def per_lead_signal_count(self):
        """
        Number of independently reconstructed named lead signals.
        """
        if self.lead_signal_extraction is None:
            return 0

        return self.lead_signal_extraction.lead_count

    @property
    def per_lead_signal_names(self):
        """
        Names belonging to the independent cell signals.
        """
        if self.lead_signal_extraction is None:
            return ()

        return self.lead_signal_extraction.lead_names

    @property
    def per_lead_signals(self):
        """
        Independently reconstructed ECG cell signals.

        These are different from lead_signals, which represents
        the legacy vertical lead-region reconstructions.
        """
        if self.lead_signal_extraction is None:
            return ()

        return self.lead_signal_extraction.leads


# =========================================================
# 1. Image Preparation and Perspective Correction
# =========================================================

def _prepare_pipeline_image(
    processed_image,
    *,
    perspective_corners,
    auto_detect_paper,
):
    paper_detection = None
    corners = perspective_corners

    if (
        corners is None
        and auto_detect_paper
    ):
        try:
            paper_detection = detect_ecg_paper_corners(
                processed_image
            )
        except ECGPaperDetectionError as exc:
            raise ECGImagePipelineError(
                "The ECG paper boundary could not be detected safely."
            ) from exc

        corners = paper_detection.corners

    if corners is None:
        return (
            processed_image,
            None,
            None,
        )

    try:
        perspective_correction = correct_ecg_perspective(
            processed_image,
            corners=corners,
        )
    except ECGPerspectiveCorrectionError as exc:
        raise ECGImagePipelineError(
            "The ECG image perspective could not be corrected safely."
        ) from exc

    corrected_processed_image = ProcessedECGImage(
        width=perspective_correction.width,
        height=perspective_correction.height,
        source_mode=processed_image.source_mode,
        grayscale=perspective_correction.grayscale,
    )

    return (
        corrected_processed_image,
        perspective_correction,
        paper_detection,
    )


# =========================================================
# 2. Existing Vertical Lead-Region Reconstruction
# =========================================================

def _reconstruct_lead_signals(
    trace_candidates,
    segmentation,
):
    lead_signals = []

    for region in segmentation.regions:
        try:
            reconstructed_signal = reconstruct_ecg_signal(
                trace_candidates,
                region_top=region.top,
                region_bottom=region.bottom,
            )
        except ECGSignalReconstructionError as exc:
            raise ECGImagePipelineError(
                "A digital ECG signal could not be reconstructed "
                f"for detected region {region.index}."
            ) from exc

        lead_signals.append(
            ECGImageLeadSignal(
                region=region,
                reconstructed_signal=reconstructed_signal,
            )
        )

    if not lead_signals:
        raise ECGImagePipelineError(
            "No ECG lead-region signals were reconstructed."
        )

    return tuple(
        lead_signals
    )


# =========================================================
# 3. Optional 2D Layout Detection
# =========================================================

def _detect_lead_layout(
    trace_candidates,
):
    try:
        return segment_ecg_lead_layout(
            trace_candidates
        )
    except ECGLeadSegmentationError as exc:
        raise ECGImagePipelineError(
            "The ECG 2D lead layout could not be "
            "segmented safely from the image."
        ) from exc


# =========================================================
# 4. Optional Lead Identification
# =========================================================

def _identify_leads_from_layout(
    lead_layout,
    *,
    layout_format,
):
    """
    Assign lead names only using an explicitly selected template.
    """

    try:
        return identify_ecg_leads(
            lead_layout,
            layout_format=layout_format,
        )
    except ECGLeadIdentificationError as exc:
        raise ECGImagePipelineError(
            "The ECG lead names could not be assigned safely."
        ) from exc


# =========================================================
# 5. NEW: Independent Per-Lead Signal Extraction
# =========================================================

def _extract_independent_lead_signals(
    processed_image,
    lead_identification,
):
    """
    Crop and reconstruct every explicitly identified ECG cell.

    Each cell is processed independently using its horizontal
    and vertical boundaries.

    An extraction failure is wrapped as an ECGImagePipelineError.
    """

    try:
        return extract_ecg_lead_signals(
            processed_image,
            lead_identification,
        )
    except ECGLeadSignalExtractionError as exc:
        raise ECGImagePipelineError(
            "The independent ECG lead signals could not be extracted safely."
        ) from exc


# =========================================================
# 6. Optional Grid Detection and Calibration
# =========================================================

def _automatically_calibrate_signals(
    processed_image,
    reconstructed_signal,
    lead_signals,
):
    try:
        grid_detection = detect_ecg_grid_scale(
            processed_image
        )
    except ECGGridDetectionError as exc:
        raise ECGImagePipelineError(
            "The ECG grid scale could not be detected safely."
        ) from exc

    pixels_per_mm = grid_detection.pixels_per_mm

    try:
        calibrated_signal = calibrate_reconstructed_signal(
            reconstructed_signal,
            pixels_per_mm=pixels_per_mm,
        )
    except ECGCalibrationError as exc:
        raise ECGImagePipelineError(
            "The reconstructed ECG signal could not be calibrated safely."
        ) from exc

    calibrated_lead_signals = []

    for lead_signal in lead_signals:
        try:
            lead_calibrated_signal = calibrate_reconstructed_signal(
                lead_signal.reconstructed_signal,
                pixels_per_mm=pixels_per_mm,
            )
        except ECGCalibrationError as exc:
            raise ECGImagePipelineError(
                "The reconstructed ECG signal for detected "
                f"region {lead_signal.index} could not be calibrated safely."
            ) from exc

        calibrated_lead_signals.append(
            replace(
                lead_signal,
                calibrated_signal=lead_calibrated_signal,
            )
        )

    return (
        grid_detection,
        calibrated_signal,
        tuple(
            calibrated_lead_signals
        ),
    )


# =========================================================
# 7. Optional ECG Quality Assessment
# =========================================================

def _assess_pipeline_quality(
    reconstructed_signal,
    *,
    lead_layout,
    grid_detection,
    calibrated_signal,
    require_layout,
    require_grid,
    require_calibration,
):
    """
    Assess ECG processing quality without making a clinical diagnosis.
    """

    try:
        return assess_ecg_processing_quality(
            reconstructed_signal,
            lead_layout=lead_layout,
            grid_detection=grid_detection,
            calibrated_signal=calibrated_signal,
            require_layout=require_layout,
            require_grid=require_grid,
            require_calibration=require_calibration,
        )
    except ECGQualityAssessmentError as exc:
        raise ECGImagePipelineError(
            "The ECG processing quality could not be assessed safely."
        ) from exc


# =========================================================
# 8. Main ECG Image Pipeline
# =========================================================

def run_ecg_image_pipeline(
    ecg_file,
    region_top=0,
    region_bottom=None,
    perspective_corners: ECGImageQuadrilateral | None = None,
    auto_detect_paper=False,
    auto_calibrate=False,
    auto_detect_layout=False,
    auto_assess_quality=False,
    lead_layout_format: str | None = None,

    # NEW: Optional extraction of twelve independent cell signals.
    auto_extract_lead_signals=False,
):
    """
    Run the complete ECG image-processing pipeline.

    Optional processing:
        - ECG paper boundary detection.
        - Perspective correction.
        - 2D lead layout detection.
        - Explicit lead identification.
        - Grid detection and calibration.
        - ECG processing quality assessment.
        - Independent extraction of twelve named cell signals.

    Lead identification requires:
        auto_detect_layout=True
        lead_layout_format="standard_3x4"

    Independent extraction additionally requires:
        auto_extract_lead_signals=True

    The lead layout format must be explicitly confirmed for the
    source ECG printout.

    Existing lead_signals represents vertical-region reconstructions.

    per_lead_signals represents independent named cell traces.

    Important:
        The current global quality assessment does not automatically
        establish the quality of every independent lead.

        Independent cell signals are not automatically calibrated
        by this new extraction option.

        No clinical ECG diagnosis or interpretation is performed.
    """

    # ---------------------------------------------------------
    # Validate Requested Options
    # ---------------------------------------------------------

    if lead_layout_format is not None and not auto_detect_layout:
        raise ECGImagePipelineError(
            "ECG lead identification requires auto_detect_layout=True."
        )

    if auto_extract_lead_signals and lead_layout_format is None:
        raise ECGImagePipelineError(
            "Independent ECG lead signal extraction requires "
            "an explicit lead_layout_format."
        )

    # ---------------------------------------------------------
    # 1. Prepare the ECG Image
    # ---------------------------------------------------------

    try:
        processed_image = process_ecg_image(
            ecg_file
        )
    except ECGImageProcessingError as exc:
        raise ECGImagePipelineError(
            "The ECG image could not be prepared for analysis."
        ) from exc

    # ---------------------------------------------------------
    # 2. Optional Paper Detection and Perspective Correction
    # ---------------------------------------------------------

    (
        processed_image,
        perspective_correction,
        paper_detection,
    ) = _prepare_pipeline_image(
        processed_image,
        perspective_corners=perspective_corners,
        auto_detect_paper=auto_detect_paper,
    )

    # ---------------------------------------------------------
    # 3. Extract ECG Trace Candidates
    # ---------------------------------------------------------

    try:
        trace_candidates = extract_trace_candidates(
            processed_image
        )
    except ECGTraceExtractionError as exc:
        raise ECGImagePipelineError(
            "ECG trace candidates could not be extracted "
            "from the image."
        ) from exc

    # ---------------------------------------------------------
    # 4. Detect Vertical Lead Regions
    # ---------------------------------------------------------

    try:
        lead_segmentation = segment_ecg_lead_regions(
            trace_candidates
        )
    except ECGLeadSegmentationError as exc:
        raise ECGImagePipelineError(
            "ECG lead regions could not be segmented "
            "from the image."
        ) from exc

    # ---------------------------------------------------------
    # 5. Optional 2D Lead Layout Detection
    # ---------------------------------------------------------

    lead_layout = None

    if auto_detect_layout:
        lead_layout = _detect_lead_layout(
            trace_candidates
        )

    # ---------------------------------------------------------
    # 5A. Optional Explicit Lead-Cell Naming
    # ---------------------------------------------------------

    lead_identification = None

    if lead_layout_format is not None:
        lead_identification = _identify_leads_from_layout(
            lead_layout,
            layout_format=lead_layout_format,
        )

    # ---------------------------------------------------------
    # 6. Reconstruct the Overall ECG Signal
    # ---------------------------------------------------------

    try:
        reconstructed_signal = reconstruct_ecg_signal(
            trace_candidates,
            region_top=region_top,
            region_bottom=region_bottom,
        )
    except ECGSignalReconstructionError as exc:
        raise ECGImagePipelineError(
            "A digital ECG signal could not be reconstructed "
            "from the requested image region."
        ) from exc

    # ---------------------------------------------------------
    # 7. Reconstruct Existing Vertical Lead-Region Signals
    # ---------------------------------------------------------

    lead_signals = _reconstruct_lead_signals(
        trace_candidates,
        lead_segmentation,
    )

    # ---------------------------------------------------------
    # 8. Optional Grid Detection and Signal Calibration
    # ---------------------------------------------------------

    grid_detection = None
    calibrated_signal = None

    if auto_calibrate:
        (
            grid_detection,
            calibrated_signal,
            lead_signals,
        ) = _automatically_calibrate_signals(
            processed_image,
            reconstructed_signal,
            lead_signals,
        )

    # ---------------------------------------------------------
    # 9. Optional ECG Processing Quality Assessment
    # ---------------------------------------------------------

    quality_assessment = None

    if auto_assess_quality:
        quality_assessment = _assess_pipeline_quality(
            reconstructed_signal,
            lead_layout=lead_layout,
            grid_detection=grid_detection,
            calibrated_signal=calibrated_signal,
            require_layout=auto_detect_layout,
            require_grid=auto_calibrate,
            require_calibration=auto_calibrate,
        )

    # ---------------------------------------------------------
    # 10. NEW: Optional Independent Per-Lead Signal Extraction
    # ---------------------------------------------------------

    lead_signal_extraction = None

    if auto_extract_lead_signals:
        lead_signal_extraction = _extract_independent_lead_signals(
            processed_image,
            lead_identification,
        )

    # ---------------------------------------------------------
    # 11. Return the Complete Pipeline Result
    # ---------------------------------------------------------

    return ECGImagePipelineResult(
        processed_image=processed_image,
        trace_candidates=trace_candidates,
        lead_segmentation=lead_segmentation,
        lead_signals=lead_signals,
        reconstructed_signal=reconstructed_signal,
        lead_layout=lead_layout,
        perspective_correction=perspective_correction,
        paper_detection=paper_detection,
        grid_detection=grid_detection,
        calibrated_signal=calibrated_signal,
        quality_assessment=quality_assessment,
        lead_identification=lead_identification,
        lead_signal_extraction=lead_signal_extraction,
    )
