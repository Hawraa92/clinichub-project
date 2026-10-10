"""
Strict ECG AI Input Contract.

This module forms the boundary between the existing ECG image-processing
pipeline and future AI inference.

Responsibilities:
    - Require twelve complete, uniquely named standard ECG leads.
    - Require successful per-lead processing-quality assessment.
    - Reject input unless all twelve leads are currently usable.
    - Require a valid detected ECG grid scale.
    - Calibrate every independently extracted named lead from pixel space
      into time in seconds and amplitude in millivolts.
    - Preserve missing samples as None.
    - Return the leads in the project's canonical ECG lead order.

This module does NOT:
    - Diagnose ECG abnormalities.
    - Produce AI predictions.
    - Produce clinical confidence.
    - Fill or interpolate missing samples.
    - Normalize or resample signals.
    - Replace physician review.

Normalization, resampling, model inference, XAI, and clinical presentation
belong to later layers.
"""

from __future__ import annotations

from dataclasses import dataclass

from ecg.services.calibration import (
    ECGCalibrationError,
    calibrate_reconstructed_signal,
)
from ecg.services.image_pipeline import (
    ECGImagePipelineResult,
)
from ecg.services.lead_identification import (
    STANDARD_ECG_LEAD_NAMES,
)


# =========================================================
# Exceptions
# =========================================================


class ECGAIInputError(ValueError):
    """
    Raised when an ECG pipeline result cannot safely be converted
    into the strict input contract required by the AI layer.
    """


# =========================================================
# AI-Ready Lead
# =========================================================


@dataclass(frozen=True)
class ECGAILeadInput:
    """
    One named ECG lead prepared for the future AI preprocessing layer.

    The signal is calibrated into physical units but is intentionally
    not normalized, resampled, interpolated, or interpreted here.

    Missing amplitude samples remain None so that later preprocessing
    must handle them explicitly rather than silently inventing data.
    """

    name: str

    time_seconds: tuple[float, ...]
    amplitude_mv: tuple[float | None, ...]

    coverage_ratio: float
    quality_level: str

    @property
    def total_sample_count(self) -> int:
        """
        Total number of sample positions represented by this lead,
        including positions whose amplitude is missing.
        """

        return len(self.amplitude_mv)

    @property
    def available_sample_count(self) -> int:
        """
        Number of samples with an available calibrated amplitude.
        """

        return sum(
            value is not None
            for value in self.amplitude_mv
        )

    @property
    def missing_sample_count(self) -> int:
        """
        Number of sample positions whose amplitude is unavailable.
        """

        return (
            self.total_sample_count
            - self.available_sample_count
        )

    @property
    def duration_seconds(self) -> float:
        """
        Duration represented by the calibrated time axis.
        """

        if not self.time_seconds:
            return 0.0

        return (
            self.time_seconds[-1]
            - self.time_seconds[0]
        )


# =========================================================
# Complete AI Input
# =========================================================


@dataclass(frozen=True)
class ECGAIInput:
    """
    Strict twelve-lead ECG input prepared for future AI preprocessing.

    The leads are always returned in STANDARD_ECG_LEAD_NAMES order.

    This object represents calibrated signal data only. It is not an AI
    prediction and must not be presented as a clinical interpretation.
    """

    layout_format: str

    source_width: int
    source_height: int

    pixels_per_mm: float
    paper_speed_mm_per_s: float
    gain_mm_per_mv: float

    leads: tuple[ECGAILeadInput, ...]

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
        """
        Confirm that this contract contains exactly the project's
        canonical twelve ECG leads in canonical order.
        """

        return (
            self.lead_count == 12
            and self.lead_names
            == tuple(STANDARD_ECG_LEAD_NAMES)
        )

    def get_lead(
        self,
        name: str,
    ) -> ECGAILeadInput | None:
        """
        Return a prepared lead by its canonical ECG name.
        """

        for lead in self.leads:
            if lead.name == name:
                return lead

        return None


# =========================================================
# Validation Helpers
# =========================================================


def _require_lead_extraction(
    pipeline_result: ECGImagePipelineResult,
):
    """
    Require independently extracted and named twelve-lead signals.
    """

    extraction = pipeline_result.lead_signal_extraction

    if extraction is None:
        raise ECGAIInputError(
            "AI input requires independently extracted "
            "named ECG lead signals."
        )

    if not extraction.complete_12_lead:
        raise ECGAIInputError(
            "AI input requires a complete set of twelve "
            "uniquely named standard ECG leads."
        )

    return extraction


def _require_lead_quality(
    pipeline_result: ECGImagePipelineResult,
):
    """
    Require per-lead processing-quality assessment.
    """

    assessment = pipeline_result.lead_quality_assessment

    if assessment is None:
        raise ECGAIInputError(
            "AI input requires per-lead ECG processing-quality "
            "assessment."
        )

    if not assessment.complete_12_lead:
        raise ECGAIInputError(
            "AI input requires processing-quality results "
            "for all twelve standard ECG leads."
        )

    if not assessment.all_usable:
        unusable_names = tuple(
            lead.name
            for lead in assessment.leads
            if not lead.usable
        )

        if unusable_names:
            joined_names = ", ".join(
                unusable_names
            )

            raise ECGAIInputError(
                "AI input was rejected because the following "
                "ECG leads did not satisfy the configured "
                f"processing-quality requirements: {joined_names}."
            )

        raise ECGAIInputError(
            "AI input was rejected because not all twelve ECG "
            "leads satisfy the configured processing-quality "
            "requirements."
        )

    return assessment


def _require_calibration_context(
    pipeline_result: ECGImagePipelineResult,
):
    """
    Require successful grid detection and the existing pipeline
    calibration context.

    The independent named leads are calibrated separately below using
    the same detected pixels-per-millimetre scale.
    """

    grid_detection = pipeline_result.grid_detection

    if grid_detection is None:
        raise ECGAIInputError(
            "AI input requires successful ECG grid detection "
            "and calibration."
        )

    calibrated_signal = pipeline_result.calibrated_signal

    if calibrated_signal is None:
        raise ECGAIInputError(
            "AI input requires successful ECG signal calibration."
        )

    pixels_per_mm = grid_detection.pixels_per_mm

    try:
        pixels_per_mm = float(
            pixels_per_mm
        )
    except (
        TypeError,
        ValueError,
    ) as exc:
        raise ECGAIInputError(
            "The detected ECG grid scale is invalid."
        ) from exc

    if pixels_per_mm <= 0:
        raise ECGAIInputError(
            "The detected ECG grid scale must be positive."
        )

    return (
        pixels_per_mm,
        calibrated_signal,
    )


def _validate_contract_alignment(
    extraction,
    quality_assessment,
):
    """
    Ensure extraction and quality assessment describe the same
    twelve-lead layout.
    """

    if (
        extraction.layout_format
        != quality_assessment.layout_format
    ):
        raise ECGAIInputError(
            "ECG lead extraction and per-lead quality assessment "
            "use different layout formats."
        )

    extracted_names = tuple(
        extraction.lead_names
    )

    assessed_names = tuple(
        quality_assessment.lead_names
    )

    if set(extracted_names) != set(assessed_names):
        raise ECGAIInputError(
            "ECG lead extraction and quality assessment "
            "do not describe the same set of leads."
        )


# =========================================================
# Public Builder
# =========================================================


def build_ecg_ai_input(
    pipeline_result: ECGImagePipelineResult,
) -> ECGAIInput:
    """
    Convert a successfully processed ECG image pipeline result into
    the strict calibrated signal contract required by future AI
    preprocessing and inference.

    Required pipeline features:
        - Explicit standard twelve-lead identification.
        - Independent named lead extraction.
        - Per-lead processing-quality assessment.
        - All twelve leads passing the configured usability checks.
        - Grid detection and calibration.

    The independent named leads are calibrated here using the same
    pixels-per-millimetre scale detected by the existing pipeline.

    No signal interpolation, normalization, resampling, prediction,
    explanation, or diagnosis is performed.
    """

    if pipeline_result is None:
        raise ECGAIInputError(
            "An ECG image pipeline result is required."
        )

    extraction = _require_lead_extraction(
        pipeline_result
    )

    quality_assessment = _require_lead_quality(
        pipeline_result
    )

    (
        pixels_per_mm,
        pipeline_calibrated_signal,
    ) = _require_calibration_context(
        pipeline_result
    )

    _validate_contract_alignment(
        extraction,
        quality_assessment,
    )

    extracted_by_name = {
        lead.name: lead
        for lead in extraction.leads
    }

    quality_by_name = {
        lead.name: lead
        for lead in quality_assessment.leads
    }

    prepared_leads = []

    calibration_parameters = None

    for lead_name in STANDARD_ECG_LEAD_NAMES:
        extracted_lead = extracted_by_name.get(
            lead_name
        )

        if extracted_lead is None:
            raise ECGAIInputError(
                "A required ECG lead is missing from the "
                f"extracted signal set: {lead_name}."
            )

        lead_quality = quality_by_name.get(
            lead_name
        )

        if lead_quality is None:
            raise ECGAIInputError(
                "A required ECG lead is missing from the "
                f"quality-assessment set: {lead_name}."
            )

        if not lead_quality.usable:
            raise ECGAIInputError(
                "AI input was rejected because ECG lead "
                f"{lead_name} is not usable."
            )

        try:
            calibrated_lead = calibrate_reconstructed_signal(
                extracted_lead.reconstructed_signal,
                pixels_per_mm=pixels_per_mm,
                paper_speed_mm_per_s=(
                    pipeline_calibrated_signal
                    .parameters
                    .paper_speed_mm_per_s
                ),
                gain_mm_per_mv=(
                    pipeline_calibrated_signal
                    .parameters
                    .gain_mm_per_mv
                ),
            )
        except ECGCalibrationError as exc:
            raise ECGAIInputError(
                "ECG lead "
                f"{lead_name} could not be calibrated safely "
                "for AI input."
            ) from exc

        if (
            len(calibrated_lead.time_seconds)
            != len(calibrated_lead.amplitude_mv)
        ):
            raise ECGAIInputError(
                "Calibrated ECG lead "
                f"{lead_name} contains inconsistent time "
                "and amplitude sample counts."
            )

        if calibration_parameters is None:
            calibration_parameters = (
                calibrated_lead.parameters
            )
        elif (
            calibrated_lead.parameters
            != calibration_parameters
        ):
            raise ECGAIInputError(
                "The twelve ECG leads do not share a consistent "
                "calibration configuration."
            )

        prepared_leads.append(
            ECGAILeadInput(
                name=lead_name,
                time_seconds=tuple(
                    calibrated_lead.time_seconds
                ),
                amplitude_mv=tuple(
                    calibrated_lead.amplitude_mv
                ),
                coverage_ratio=float(
                    lead_quality.coverage_ratio
                ),
                quality_level=str(
                    lead_quality.quality_level
                ),
            )
        )

    if calibration_parameters is None:
        raise ECGAIInputError(
            "No calibrated ECG leads were produced for AI input."
        )

    ai_input = ECGAIInput(
        layout_format=extraction.layout_format,
        source_width=extraction.source_width,
        source_height=extraction.source_height,
        pixels_per_mm=(
            calibration_parameters.pixels_per_mm
        ),
        paper_speed_mm_per_s=(
            calibration_parameters.paper_speed_mm_per_s
        ),
        gain_mm_per_mv=(
            calibration_parameters.gain_mm_per_mv
        ),
        leads=tuple(
            prepared_leads
        ),
    )

    if not ai_input.complete_12_lead:
        raise ECGAIInputError(
            "The generated AI input does not contain the "
            "complete canonical twelve-lead ECG set."
        )

    return ai_input
