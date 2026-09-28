
"""
Tests for ECG Per-Lead Quality Assessment Foundation.

This module verifies independent engineering-quality assessment
for twelve reconstructed ECG lead signals.

Covered scenarios:
    - All twelve leads have high processing quality.
    - One lead has acceptable quality.
    - One lead has insufficient quality.
    - Individual quality metrics remain independent.
    - Aggregate quality reflects the individual lead results.
    - Custom quality thresholds are respected.
    - Invalid extraction results are rejected.
    - Assessment failures are safely associated with a lead.

These assessments do not establish clinical or diagnostic accuracy.
"""

from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import call, patch

from django.test import SimpleTestCase

from ecg.services.lead_quality_assessment import (
    ECGIndividualLeadQuality,
    ECGLeadQualityAssessmentError,
    ECGLeadQualityAssessmentResult,
    assess_ecg_lead_quality,
)

from ecg.services.lead_segmentation import (
    ECGLeadLayoutCell,
)

from ecg.services.lead_signal_extraction import (
    ECGExtractedLeadSignal,
    ECGLeadSignalExtractionResult,
)

from ecg.services.quality_assessment import (
    ECGQualityAssessmentError,
    assess_ecg_processing_quality,
)


class ECGLeadQualityAssessmentTests(SimpleTestCase):

    # =========================================================
    # Fixtures
    # =========================================================

    LEAD_TEMPLATE = (
        ("I", "aVR", "V1", "V4"),
        ("II", "aVL", "V2", "V5"),
        ("III", "aVF", "V3", "V6"),
    )

    def create_signal(
        self,
        *,
        coverage_ratio=1.0,
        sample_count=20,
        missing_count=0,
    ):
        """
        Create a synthetic reconstruction-quality fixture.

        The test focuses on quality metrics rather than the
        underlying ECG waveform morphology.
        """

        return SimpleNamespace(
            coverage_ratio=coverage_ratio,
            sample_count=sample_count,
            missing_count=missing_count,
        )

    def create_extraction_result(self):
        """
        Create twelve independently named synthetic ECG leads.

        Layout:
            Three rows and four columns.

        Each cell:
            Width = 20 pixels.
            Height = 12 pixels.
        """

        extracted_leads = []
        cell_index = 1

        for row_index, row_names in enumerate(
            self.LEAD_TEMPLATE,
            start=1,
        ):
            for column_index, lead_name in enumerate(
                row_names,
                start=1,
            ):

                left = (column_index - 1) * 20
                right = column_index * 20

                top = (row_index - 1) * 12
                bottom = row_index * 12

                cell = ECGLeadLayoutCell(
                    index=cell_index,
                    row_index=row_index,
                    column_index=column_index,
                    left=left,
                    right=right,
                    top=top,
                    bottom=bottom,
                    active_left=left,
                    active_right=right,
                    active_top=top + 1,
                    active_bottom=bottom - 1,
                    candidate_pixel_count=20,
                )

                extracted_leads.append(
                    ECGExtractedLeadSignal(
                        name=lead_name,
                        row_index=row_index,
                        column_index=column_index,
                        cell=cell,
                        reconstructed_signal=self.create_signal(),
                        image_left=left,
                        image_top=top,
                    )
                )

                cell_index += 1

        return ECGLeadSignalExtractionResult(
            layout_format="standard_3x4",
            source_width=80,
            source_height=36,
            leads=tuple(extracted_leads),
        )

    def change_lead(
        self,
        extraction_result,
        lead_name,
        **changes,
    ):
        """
        Return a modified extraction result without changing
        its original frozen dataclass instances.
        """

        leads = list(extraction_result.leads)

        for index, lead in enumerate(leads):

            if lead.name == lead_name:

                leads[index] = replace(
                    lead,
                    **changes,
                )

                return replace(
                    extraction_result,
                    leads=tuple(leads),
                )

        raise AssertionError(
            f"Test fixture does not contain lead {lead_name}."
        )

    def change_lead_signal(
        self,
        extraction_result,
        lead_name,
        *,
        coverage_ratio,
        sample_count=20,
        missing_count=0,
    ):
        """
        Modify the signal quality of one lead only.
        """

        replacement_signal = self.create_signal(
            coverage_ratio=coverage_ratio,
            sample_count=sample_count,
            missing_count=missing_count,
        )

        return self.change_lead(
            extraction_result,
            lead_name,
            reconstructed_signal=replacement_signal,
        )

    # =========================================================
    # 1. Complete High-Quality Assessment
    # =========================================================

    def test_assesses_all_twelve_leads_independently(self):
        extraction = self.create_extraction_result()

        result = assess_ecg_lead_quality(
            extraction
        )

        self.assertIsInstance(
            result,
            ECGLeadQualityAssessmentResult,
        )

        self.assertEqual(
            result.layout_format,
            "standard_3x4",
        )

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

    def test_all_complete_leads_have_high_quality(self):
        extraction = self.create_extraction_result()

        result = assess_ecg_lead_quality(
            extraction
        )

        self.assertTrue(result.all_usable)
        self.assertTrue(result.all_high_quality)

        self.assertEqual(
            result.quality_level,
            "high",
        )

        self.assertEqual(
            result.high_quality_count,
            12,
        )

        self.assertEqual(
            result.acceptable_count,
            0,
        )

        self.assertEqual(
            result.insufficient_count,
            0,
        )

        self.assertEqual(
            result.unusable_lead_names,
            (),
        )

    def test_each_lead_has_individual_quality_result(self):
        extraction = self.create_extraction_result()

        result = assess_ecg_lead_quality(
            extraction
        )

        for lead in result.leads:

            with self.subTest(lead=lead.name):

                self.assertIsInstance(
                    lead,
                    ECGIndividualLeadQuality,
                )

                self.assertTrue(lead.usable)
                self.assertTrue(lead.high_quality)

                self.assertFalse(
                    lead.insufficient_quality
                )

                self.assertEqual(
                    lead.quality_level,
                    "high",
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

                self.assertEqual(
                    lead.coverage_percent,
                    100.0,
                )

                self.assertEqual(lead.reasons, ())
                self.assertEqual(lead.warnings, ())

    def test_individual_quality_preserves_extracted_lead(self):
        extraction = self.create_extraction_result()

        result = assess_ecg_lead_quality(
            extraction
        )

        for extracted, assessed in zip(
            extraction.leads,
            result.leads,
        ):

            with self.subTest(lead=extracted.name):

                self.assertIs(
                    assessed.extracted_lead,
                    extracted,
                )

                self.assertIs(
                    assessed.reconstructed_signal,
                    extracted.reconstructed_signal,
                )

                self.assertEqual(
                    assessed.name,
                    extracted.name,
                )

                self.assertEqual(
                    assessed.row_index,
                    extracted.row_index,
                )

                self.assertEqual(
                    assessed.column_index,
                    extracted.column_index,
                )

    # =========================================================
    # 2. Result Access
    # =========================================================

    def test_get_lead_returns_correct_assessment(self):
        extraction = self.create_extraction_result()

        result = assess_ecg_lead_quality(
            extraction
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

    def test_get_lead_uses_exact_name(self):
        extraction = self.create_extraction_result()

        result = assess_ecg_lead_quality(
            extraction
        )

        self.assertIsNotNone(
            result.get_lead("aVR")
        )

        self.assertIsNone(
            result.get_lead("avr")
        )

        self.assertIsNone(
            result.get_lead("UNKNOWN")
        )

        self.assertIsNone(
            result.get_lead("V7")
        )

    def test_coverage_mapping_contains_all_leads(self):
        extraction = self.create_extraction_result()

        result = assess_ecg_lead_quality(
            extraction
        )

        coverage = result.coverage_by_lead

        self.assertEqual(
            len(coverage),
            12,
        )

        self.assertEqual(
            set(coverage),
            set(result.lead_names),
        )

        for coverage_ratio in coverage.values():
            self.assertEqual(
                coverage_ratio,
                1.0,
            )

    # =========================================================
    # 3. Acceptable Quality
    # =========================================================

    def test_one_acceptable_lead_changes_aggregate_quality(self):
        extraction = self.create_extraction_result()

        extraction = self.change_lead_signal(
            extraction,
            "V6",
            coverage_ratio=0.95,
            sample_count=20,
            missing_count=1,
        )

        result = assess_ecg_lead_quality(
            extraction
        )

        lead_v6 = result.get_lead("V6")

        self.assertTrue(lead_v6.usable)

        self.assertEqual(
            lead_v6.quality_level,
            "acceptable",
        )

        self.assertFalse(
            lead_v6.high_quality
        )

        self.assertTrue(result.all_usable)

        self.assertFalse(
            result.all_high_quality
        )

        self.assertEqual(
            result.quality_level,
            "acceptable",
        )

        self.assertEqual(
            result.high_quality_count,
            11,
        )

        self.assertEqual(
            result.acceptable_count,
            1,
        )

        self.assertEqual(
            result.insufficient_count,
            0,
        )

    def test_partial_coverage_is_recorded_per_lead(self):
        extraction = self.create_extraction_result()

        extraction = self.change_lead_signal(
            extraction,
            "V6",
            coverage_ratio=0.95,
            missing_count=1,
        )

        result = assess_ecg_lead_quality(
            extraction
        )

        lead_v6 = result.get_lead("V6")
        lead_i = result.get_lead("I")

        self.assertAlmostEqual(
            lead_v6.coverage_percent,
            95.0,
        )

        self.assertEqual(
            lead_v6.missing_count,
            1,
        )

        self.assertEqual(
            lead_i.coverage_percent,
            100.0,
        )

        self.assertEqual(
            result.coverage_by_lead["V6"],
            0.95,
        )

        self.assertEqual(
            result.coverage_by_lead["I"],
            1.0,
        )

    # =========================================================
    # 4. Insufficient Quality
    # =========================================================

    def test_one_insufficient_lead_makes_aggregate_insufficient(
        self,
    ):
        """
        Critical test:

        Eleven usable leads must not hide the failure
        of the twelfth required lead.
        """

        extraction = self.create_extraction_result()

        extraction = self.change_lead_signal(
            extraction,
            "V6",
            coverage_ratio=0.80,
            sample_count=20,
            missing_count=4,
        )

        result = assess_ecg_lead_quality(
            extraction
        )

        self.assertTrue(
            result.complete_12_lead
        )

        self.assertFalse(
            result.all_usable
        )

        self.assertFalse(
            result.all_high_quality
        )

        self.assertEqual(
            result.quality_level,
            "insufficient",
        )

        self.assertEqual(
            result.high_quality_count,
            11,
        )

        self.assertEqual(
            result.insufficient_count,
            1,
        )

        self.assertEqual(
            result.unusable_lead_names,
            ("V6",),
        )

    def test_insufficient_lead_exposes_its_own_reasons(self):
        extraction = self.create_extraction_result()

        extraction = self.change_lead_signal(
            extraction,
            "V6",
            coverage_ratio=0.80,
            sample_count=20,
            missing_count=4,
        )

        result = assess_ecg_lead_quality(
            extraction
        )

        lead_v6 = result.get_lead("V6")

        self.assertFalse(lead_v6.usable)

        self.assertTrue(
            lead_v6.insufficient_quality
        )

        self.assertEqual(
            lead_v6.quality_level,
            "insufficient",
        )

        self.assertTrue(
            lead_v6.reasons
        )

        self.assertEqual(
            result.get_lead("I").reasons,
            (),
        )

    def test_multiple_insufficient_leads_are_reported(self):
        extraction = self.create_extraction_result()

        extraction = self.change_lead_signal(
            extraction,
            "II",
            coverage_ratio=0.70,
            missing_count=6,
        )

        extraction = self.change_lead_signal(
            extraction,
            "V6",
            coverage_ratio=0.80,
            missing_count=4,
        )

        result = assess_ecg_lead_quality(
            extraction
        )

        self.assertEqual(
            result.insufficient_count,
            2,
        )

        self.assertEqual(
            result.unusable_lead_names,
            ("II", "V6"),
        )

        self.assertEqual(
            result.quality_level,
            "insufficient",
        )

    def test_low_sample_count_is_assessed_independently(self):
        extraction = self.create_extraction_result()

        extraction = self.change_lead_signal(
            extraction,
            "V3",
            coverage_ratio=1.0,
            sample_count=5,
            missing_count=0,
        )

        result = assess_ecg_lead_quality(
            extraction
        )

        lead_v3 = result.get_lead("V3")

        self.assertFalse(lead_v3.usable)

        self.assertEqual(
            lead_v3.quality_level,
            "insufficient",
        )

        self.assertEqual(
            result.unusable_lead_names,
            ("V3",),
        )

    def test_insufficient_quality_returns_result_not_exception(self):
        extraction = self.create_extraction_result()

        extraction = self.change_lead_signal(
            extraction,
            "aVF",
            coverage_ratio=0.50,
            missing_count=10,
        )

        result = assess_ecg_lead_quality(
            extraction
        )

        self.assertIsInstance(
            result,
            ECGLeadQualityAssessmentResult,
        )

        self.assertFalse(result.all_usable)

        self.assertEqual(
            result.unusable_lead_names,
            ("aVF",),
        )

    # =========================================================
    # 5. Custom Quality Thresholds
    # =========================================================

    def test_custom_minimum_coverage_can_change_usability(self):
        extraction = self.create_extraction_result()

        extraction = self.change_lead_signal(
            extraction,
            "V6",
            coverage_ratio=0.80,
            missing_count=4,
        )

        default_result = assess_ecg_lead_quality(
            extraction
        )

        custom_result = assess_ecg_lead_quality(
            extraction,
            min_coverage_ratio=0.75,
        )

        self.assertFalse(
            default_result.get_lead("V6").usable
        )

        self.assertTrue(
            custom_result.get_lead("V6").usable
        )

        self.assertEqual(
            custom_result.get_lead("V6").quality_level,
            "acceptable",
        )

        self.assertTrue(
            custom_result.all_usable
        )

    def test_custom_minimum_sample_count_is_applied(self):
        extraction = self.create_extraction_result()

        result = assess_ecg_lead_quality(
            extraction,
            min_sample_count=21,
        )

        self.assertFalse(result.all_usable)

        self.assertEqual(
            result.insufficient_count,
            12,
        )

        self.assertEqual(
            result.quality_level,
            "insufficient",
        )

    def test_custom_high_quality_threshold_is_applied(self):
        extraction = self.create_extraction_result()

        result = assess_ecg_lead_quality(
            extraction,
            high_quality_coverage_ratio=1.0,
        )

        self.assertTrue(result.all_usable)
        self.assertTrue(result.all_high_quality)

        self.assertEqual(
            result.high_quality_count,
            12,
        )

    def test_forwards_quality_configuration_to_every_lead(self):
        extraction = self.create_extraction_result()

        with patch(
            "ecg.services.lead_quality_assessment."
            "assess_ecg_processing_quality",
            wraps=assess_ecg_processing_quality,
        ) as assessment_mock:

            result = assess_ecg_lead_quality(
                extraction,
                min_coverage_ratio=0.80,
                high_quality_coverage_ratio=0.95,
                min_sample_count=8,
            )

        self.assertEqual(result.lead_count, 12)

        self.assertEqual(
            assessment_mock.call_count,
            12,
        )

        for index, extracted_lead in enumerate(
            extraction.leads
        ):

            with self.subTest(lead=extracted_lead.name):

                self.assertEqual(
                    assessment_mock.call_args_list[index],
                    call(
                        extracted_lead.reconstructed_signal,
                        min_coverage_ratio=0.80,
                        high_quality_coverage_ratio=0.95,
                        min_sample_count=8,
                    ),
                )

    # =========================================================
    # 6. Invalid Input Validation
    # =========================================================

    def test_rejects_invalid_extraction_result_type(self):
        with self.assertRaisesRegex(
            ECGLeadQualityAssessmentError,
            "A valid ECGLeadSignalExtractionResult is required",
        ):
            assess_ecg_lead_quality(
                "invalid-extraction-result"
            )

    def test_rejects_missing_extracted_lead(self):
        extraction = self.create_extraction_result()

        incomplete = replace(
            extraction,
            leads=extraction.leads[:-1],
        )

        with self.assertRaisesRegex(
            ECGLeadQualityAssessmentError,
            "Twelve unique extracted ECG lead signals",
        ):
            assess_ecg_lead_quality(
                incomplete
            )

    def test_rejects_duplicate_extracted_lead_name(self):
        extraction = self.create_extraction_result()

        duplicate = self.change_lead(
            extraction,
            "V6",
            name="I",
        )

        with self.assertRaises(
            ECGLeadQualityAssessmentError
        ):
            assess_ecg_lead_quality(
                duplicate
            )

    def test_rejects_unsupported_extracted_lead_name(self):
        extraction = self.create_extraction_result()

        invalid = self.change_lead(
            extraction,
            "V6",
            name="V7",
        )

        with self.assertRaises(
            ECGLeadQualityAssessmentError
        ):
            assess_ecg_lead_quality(
                invalid
            )

    def test_rejects_duplicate_extracted_cell_position(self):
        extraction = self.create_extraction_result()

        first_lead = extraction.leads[0]

        invalid = self.change_lead(
            extraction,
            "V6",
            row_index=first_lead.row_index,
            column_index=first_lead.column_index,
        )

        with self.assertRaisesRegex(
            ECGLeadQualityAssessmentError,
            "Duplicate extracted ECG cell position",
        ):
            assess_ecg_lead_quality(
                invalid
            )

    def test_rejects_inconsistent_cell_coordinates(self):
        extraction = self.create_extraction_result()

        invalid = self.change_lead(
            extraction,
            "I",
            row_index=9,
        )

        with self.assertRaisesRegex(
            ECGLeadQualityAssessmentError,
            "inconsistent cell coordinates",
        ):
            assess_ecg_lead_quality(
                invalid
            )

    def test_rejects_lead_without_reconstructed_signal(self):
        extraction = self.create_extraction_result()

        invalid = self.change_lead(
            extraction,
            "V6",
            reconstructed_signal=None,
        )

        with self.assertRaisesRegex(
            ECGLeadQualityAssessmentError,
            "has no reconstructed signal",
        ):
            assess_ecg_lead_quality(
                invalid
            )

    # =========================================================
    # 7. Assessment Failure Handling
    # =========================================================

    def test_wraps_assessment_failure_with_lead_name(self):
        extraction = self.create_extraction_result()

        with patch(
            "ecg.services.lead_quality_assessment."
            "assess_ecg_processing_quality",
            side_effect=ECGQualityAssessmentError(
                "Simulated quality assessment failure."
            ),
        ):

            with self.assertRaises(
                ECGLeadQualityAssessmentError
            ) as context:

                assess_ecg_lead_quality(
                    extraction
                )

        self.assertIn(
            "ECG lead I",
            str(context.exception),
        )

        self.assertIsInstance(
            context.exception.__cause__,
            ECGQualityAssessmentError,
        )

    def test_invalid_signal_metrics_are_wrapped_safely(self):
        extraction = self.create_extraction_result()

        invalid = self.change_lead_signal(
            extraction,
            "V6",
            coverage_ratio=1.0,
            sample_count=20,
            missing_count=21,
        )

        with self.assertRaises(
            ECGLeadQualityAssessmentError
        ) as context:

            assess_ecg_lead_quality(
                invalid
            )

        self.assertIn(
            "ECG lead V6",
            str(context.exception),
        )

        self.assertIsInstance(
            context.exception.__cause__,
            ECGQualityAssessmentError,
        )

    def test_assessment_does_not_modify_original_extraction(self):
        extraction = self.create_extraction_result()

        original_leads = extraction.leads

        result = assess_ecg_lead_quality(
            extraction
        )

        self.assertIs(
            extraction.leads,
            original_leads,
        )

        self.assertEqual(
            len(extraction.leads),
            12,
        )

        for index, assessed_lead in enumerate(
            result.leads
        ):
            self.assertIs(
                assessed_lead.extracted_lead,
                extraction.leads[index],
            )
