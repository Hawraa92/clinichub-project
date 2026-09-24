from dataclasses import dataclass

from ecg.services.image_processing import (
    ECGImageProcessingError,
    ProcessedECGImage,
    process_ecg_image,
)
from ecg.services.lead_segmentation import (
    ECGLeadRegion,
    ECGLeadSegmentationError,
    ECGLeadSegmentationResult,
    segment_ecg_lead_regions,
)
from ecg.services.perspective import (
    ECGImageQuadrilateral,
    ECGPerspectiveCorrectionError,
    RectifiedECGImage,
    correct_ecg_perspective,
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


class ECGImagePipelineError(ValueError):
    """Raised when the ECG image pipeline cannot complete safely."""


@dataclass(frozen=True)
class ECGImageLeadSignal:
    region: ECGLeadRegion
    reconstructed_signal: ReconstructedECGSignal

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


@dataclass
class ECGImagePipelineResult:
    processed_image: ProcessedECGImage
    trace_candidates: ECGTraceCandidates
    lead_segmentation: ECGLeadSegmentationResult
    lead_signals: tuple[ECGImageLeadSignal, ...]
    reconstructed_signal: ReconstructedECGSignal
    perspective_correction: RectifiedECGImage | None = None

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


def _prepare_pipeline_image(
    processed_image,
    *,
    perspective_corners,
):
    if perspective_corners is None:
        return (
            processed_image,
            None,
        )

    try:
        perspective_correction = correct_ecg_perspective(
            processed_image,
            corners=perspective_corners,
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
    )


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

    return tuple(lead_signals)


def run_ecg_image_pipeline(
    ecg_file,
    region_top=0,
    region_bottom=None,
    perspective_corners: ECGImageQuadrilateral | None = None,
):
    try:
        processed_image = process_ecg_image(
            ecg_file
        )
    except ECGImageProcessingError as exc:
        raise ECGImagePipelineError(
            "The ECG image could not be prepared for analysis."
        ) from exc

    (
        processed_image,
        perspective_correction,
    ) = _prepare_pipeline_image(
        processed_image,
        perspective_corners=perspective_corners,
    )

    try:
        trace_candidates = extract_trace_candidates(
            processed_image
        )
    except ECGTraceExtractionError as exc:
        raise ECGImagePipelineError(
            "ECG trace candidates could not be extracted "
            "from the image."
        ) from exc

    try:
        lead_segmentation = segment_ecg_lead_regions(
            trace_candidates
        )
    except ECGLeadSegmentationError as exc:
        raise ECGImagePipelineError(
            "ECG lead regions could not be segmented "
            "from the image."
        ) from exc

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

    lead_signals = _reconstruct_lead_signals(
        trace_candidates,
        lead_segmentation,
    )

    return ECGImagePipelineResult(
        processed_image=processed_image,
        trace_candidates=trace_candidates,
        lead_segmentation=lead_segmentation,
        lead_signals=lead_signals,
        reconstructed_signal=reconstructed_signal,
        perspective_correction=perspective_correction,
    )