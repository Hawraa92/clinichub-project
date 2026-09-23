from dataclasses import dataclass

from ecg.services.image_processing import (
    ECGImageProcessingError,
    ProcessedECGImage,
    process_ecg_image,
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


@dataclass
class ECGImagePipelineResult:
    processed_image: ProcessedECGImage
    trace_candidates: ECGTraceCandidates
    reconstructed_signal: ReconstructedECGSignal

    @property
    def width(self):
        return self.processed_image.width

    @property
    def height(self):
        return self.processed_image.height

    @property
    def coverage_ratio(self):
        return (
            self.reconstructed_signal.coverage_ratio
        )

    @property
    def signal_values(self):
        return (
            self.reconstructed_signal.signal_values
        )

    @property
    def x_positions(self):
        return (
            self.reconstructed_signal.x_positions
        )


def run_ecg_image_pipeline(
    ecg_file,
    region_top=0,
    region_bottom=None,
):
    try:
        processed_image = process_ecg_image(
            ecg_file
        )
    except ECGImageProcessingError as exc:
        raise ECGImagePipelineError(
            "The ECG image could not be prepared for analysis."
        ) from exc

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
        reconstructed_signal = reconstruct_ecg_signal(
            trace_candidates,
            region_top=region_top,
            region_bottom=region_bottom,
        )
    except ECGSignalReconstructionError as exc:
        raise ECGImagePipelineError(
            "A digital ECG signal could not be reconstructed "
            "from the image."
        ) from exc

    return ECGImagePipelineResult(
        processed_image=processed_image,
        trace_candidates=trace_candidates,
        reconstructed_signal=reconstructed_signal,
    )