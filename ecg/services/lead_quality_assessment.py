
"""
ECG Per-Lead Quality Assessment Foundation.

This module evaluates the processing quality of independently
reconstructed ECG lead signals.

Each lead is assessed separately using the existing ECG processing
quality assessment service.

Important:
    This module evaluates data completeness and processing quality.

    It does not evaluate diagnostic accuracy, establish clinical
    confidence, or perform ECG interpretation.
"""

from dataclasses import dataclass

from ecg.services.lead_identification import (
    STANDARD_ECG_LEAD_NAMES,
)

from ecg.services.lead_signal_extraction import (
    ECGExtractedLeadSignal,
    ECGLeadSignalExtractionResult,
)

from ecg.services.quality_assessment import (
    DEFAULT_ECG_MIN_USABLE_COVERAGE_RATIO,
    DEFAULT_ECG_HIGH_QUALITY_COVERAGE_RATIO,
    DEFAULT_ECG_MIN_USABLE_SAMPLE_COUNT,
    ECGQualityAssessmentError,
    ECGQualityAssessmentResult,
    assess_ecg_processing_quality,
)


# =========================================================
# Exception
# =========================================================

class ECGLeadQualityAssessmentError(ValueError):
    """
    Raised when per-lead quality assessment cannot be
    performed safely.
    """


# =========================================================
# Individual Lead Quality Result
# =========================================================

@dataclass(frozen=True)
class ECGIndividualLeadQuality:
    """
    Processing quality assessment for one named ECG lead.

    The original extracted lead is preserved to maintain
    access to its signal and spatial information.
    """

    name: str
    row_index: int
    column_index: int

    extracted_lead: ECGExtractedLeadSignal
    assessment: ECGQualityAssessmentResult

    @property
    def usable(self) -> bool:
        return self.assessment.usable

    @property
    def quality_level(self) -> str:
        return self.assessment.quality_level

    @property
    def high_quality(self) -> bool:
        return self.assessment.high_quality

    @property
    def insufficient_quality(self) -> bool:
        return self.assessment.insufficient_quality

    @property
    def coverage_ratio(self) -> float:
        return self.assessment.coverage_ratio

    @property
    def coverage_percent(self) -> float:
        return self.assessment.coverage_percent

    @property
    def sample_count(self) -> int:
        return self.assessment.sample_count

    @property
    def missing_count(self) -> int:
        return self.assessment.missing_count

    @property
    def reasons(self) -> tuple[str, ...]:
        return self.assessment.reasons

    @property
    def warnings(self) -> tuple[str, ...]:
        return self.assessment.warnings

    @property
    def reconstructed_signal(self):
        return self.extracted_lead.reconstructed_signal


# =========================================================
# Complete Per-Lead Quality Result
# =========================================================

@dataclass(frozen=True)
class ECGLeadQualityAssessmentResult:
    """
    Collection of processing quality assessments for
    twelve independently reconstructed ECG leads.
    """

    layout_format: str

    leads: tuple[ECGIndividualLeadQuality, ...]

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

    @property
    def all_usable(self) -> bool:
        """
        True only when all twelve leads satisfy the configured
        processing-quality requirements.
        """

        return (
            self.complete_12_lead
            and all(
                lead.usable
                for lead in self.leads
            )
        )

    @property
    def all_high_quality(self) -> bool:
        return (
            self.complete_12_lead
            and all(
                lead.high_quality
                for lead in self.leads
            )
        )

    @property
    def high_quality_count(self) -> int:
        return sum(
            lead.quality_level == "high"
            for lead in self.leads
        )

    @property
    def acceptable_count(self) -> int:
        return sum(
            lead.quality_level == "acceptable"
            for lead in self.leads
        )

    @property
    def insufficient_count(self) -> int:
        return sum(
            lead.quality_level == "insufficient"
            for lead in self.leads
        )

    @property
    def unusable_lead_names(self) -> tuple[str, ...]:
        """
        Return the names of leads that failed the configured
        processing-quality requirements.
        """

        return tuple(
            lead.name
            for lead in self.leads
            if not lead.usable
        )

    @property
    def quality_level(self) -> str:
        """
        Aggregate engineering quality classification.

        This is not a clinical quality or diagnostic score.
        """

        if not self.all_usable:
            return "insufficient"

        if self.all_high_quality:
            return "high"

        return "acceptable"

    @property
    def coverage_by_lead(self) -> dict[str, float]:
        return {
            lead.name: lead.coverage_ratio
            for lead in self.leads
        }

    def get_lead(
        self,
        name: str,
    ) -> ECGIndividualLeadQuality | None:
        """
        Retrieve an individual quality assessment by
        its exact ECG lead name.
        """

        for lead in self.leads:
            if lead.name == name:
                return lead

        return None


# =========================================================
# Input Validation
# =========================================================

def _validate_extracted_leads(
    extraction_result: ECGLeadSignalExtractionResult,
) -> tuple[ECGExtractedLeadSignal, ...]:
    """
    Validate the independent ECG signal extraction result
    before starting quality assessment.
    """

    if not isinstance(
        extraction_result,
        ECGLeadSignalExtractionResult,
    ):
        raise ECGLeadQualityAssessmentError(
            "A valid ECGLeadSignalExtractionResult is required."
        )

    if not extraction_result.complete_12_lead:
        raise ECGLeadQualityAssessmentError(
            "Twelve unique extracted ECG lead signals "
            "are required for per-lead quality assessment."
        )

    seen_names = set()
    seen_positions = set()

    for lead in extraction_result.leads:

        if not isinstance(
            lead,
            ECGExtractedLeadSignal,
        ):
            raise ECGLeadQualityAssessmentError(
                "The extraction result contains an invalid ECG lead."
            )

        if lead.name not in STANDARD_ECG_LEAD_NAMES:
            raise ECGLeadQualityAssessmentError(
                "An unsupported ECG lead name was detected."
            )

        if lead.name in seen_names:
            raise ECGLeadQualityAssessmentError(
                "Duplicate ECG lead name detected."
            )

        position = (
            lead.row_index,
            lead.column_index,
        )

        if position in seen_positions:
            raise ECGLeadQualityAssessmentError(
                "Duplicate extracted ECG cell position detected."
            )

        if (
            lead.cell.row_index != lead.row_index
            or lead.cell.column_index != lead.column_index
        ):
            raise ECGLeadQualityAssessmentError(
                f"Lead {lead.name} contains inconsistent "
                "cell coordinates."
            )

        if lead.reconstructed_signal is None:
            raise ECGLeadQualityAssessmentError(
                f"Lead {lead.name} has no reconstructed signal."
            )

        seen_names.add(lead.name)
        seen_positions.add(position)

    return extraction_result.leads


# =========================================================
# Individual Quality Assessment
# =========================================================

def _assess_single_lead(
    extracted_lead: ECGExtractedLeadSignal,
    *,
    min_coverage_ratio: float,
    high_quality_coverage_ratio: float,
    min_sample_count: int,
) -> ECGIndividualLeadQuality:
    """
    Apply the existing processing-quality evaluator
    to one independently reconstructed ECG signal.
    """

    try:
        assessment = assess_ecg_processing_quality(
            extracted_lead.reconstructed_signal,
            min_coverage_ratio=min_coverage_ratio,
            high_quality_coverage_ratio=high_quality_coverage_ratio,
            min_sample_count=min_sample_count,
        )

    except ECGQualityAssessmentError as exc:
        raise ECGLeadQualityAssessmentError(
            f"The processing quality of ECG lead "
            f"{extracted_lead.name} could not be assessed safely."
        ) from exc

    return ECGIndividualLeadQuality(
        name=extracted_lead.name,
        row_index=extracted_lead.row_index,
        column_index=extracted_lead.column_index,
        extracted_lead=extracted_lead,
        assessment=assessment,
    )


# =========================================================
# Public Assessment Function
# =========================================================

def assess_ecg_lead_quality(
    extraction_result: ECGLeadSignalExtractionResult,
    *,
    min_coverage_ratio: float = (
        DEFAULT_ECG_MIN_USABLE_COVERAGE_RATIO
    ),
    high_quality_coverage_ratio: float = (
        DEFAULT_ECG_HIGH_QUALITY_COVERAGE_RATIO
    ),
    min_sample_count: int = (
        DEFAULT_ECG_MIN_USABLE_SAMPLE_COUNT
    ),
) -> ECGLeadQualityAssessmentResult:
    """
    Assess processing quality independently for twelve ECG leads.

    Parameters
    ----------
    extraction_result:
        A completed independent lead signal extraction result.

    min_coverage_ratio:
        Minimum coverage required for an individual lead
        to be classified as usable.

    high_quality_coverage_ratio:
        Coverage threshold used for the high-quality
        processing classification.

    min_sample_count:
        Minimum required reconstructed samples per lead.

    Returns
    -------
    ECGLeadQualityAssessmentResult:
        Individual quality assessments and an aggregate
        engineering-quality summary.

    Notes
    -----
    A lead with insufficient coverage is recorded as unusable.
    This does not automatically raise a service exception.

    Exceptions are reserved for invalid inputs or failure
    of the assessment process itself.

    The assessment cannot evaluate a missing lead if the
    preceding extraction stage failed completely.

    These classifications must not be interpreted as
    diagnostic reliability or clinical confidence.
    """

    extracted_leads = _validate_extracted_leads(
        extraction_result
    )

    individual_results = []

    for extracted_lead in extracted_leads:

        individual_quality = _assess_single_lead(
            extracted_lead,
            min_coverage_ratio=min_coverage_ratio,
            high_quality_coverage_ratio=high_quality_coverage_ratio,
            min_sample_count=min_sample_count,
        )

        individual_results.append(
            individual_quality
        )

    result = ECGLeadQualityAssessmentResult(
        layout_format=extraction_result.layout_format,
        leads=tuple(individual_results),
    )

    if not result.complete_12_lead:
        raise ECGLeadQualityAssessmentError(
            "The assessment did not produce twelve unique "
            "ECG lead quality results."
        )

    return result
