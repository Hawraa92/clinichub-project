"""
Tests for the strict ECG AI input contract.

These tests verify the boundary between the existing ECG
image-processing pipeline and the future AI inference layer.

The contract must:
    - Require twelve complete standard ECG leads.
    - Require per-lead processing-quality assessment.
    - Reject unusable leads.
    - Require successful grid detection and calibration context.
    - Preserve canonical ECG lead ordering.
    - Calibrate every named lead using the existing calibration service.
    - Preserve missing samples rather than silently filling them.
    - Reject inconsistent calibration across leads.

No clinical prediction, diagnosis, or XAI interpretation is tested here.
"""

from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase

from ecg.services.ai.input_contract import (
    ECGAIInputError,
    build_ecg_ai_input,
)
from ecg.services.calibration import (
    ECGCalibrationError,
    ECGCalibrationParameters,
)
from ecg.services.lead_identification import (
    STANDARD_ECG_LEAD_NAMES,
)


class ECGAIInputContractTests(SimpleTestCase):
    """
    Unit tests for the strict ECG-to-AI input boundary.
    """

    def _build_extracted_leads(
        self,
        *,
        lead_names=None,
    ):
        """
        Build lightweight named extracted-lead objects.

        The AI contract only requires:
            - name
            - reconstructed_signal

        The calibration service is mocked in these tests so that this
        test module remains focused on the AI input contract itself.
        """

        if lead_names is None:
            lead_names = tuple(
                STANDARD_ECG_LEAD_NAMES
            )

        return tuple(
            SimpleNamespace(
                name=lead_name,
                reconstructed_signal=SimpleNamespace(
                    lead_name=lead_name,
                ),
            )
            for lead_name in lead_names
        )

    def _build_quality_leads(
        self,
        *,
        lead_names=None,
        unusable_names=(),
    ):
        """
        Build lightweight per-lead processing-quality results.
        """

        if lead_names is None:
            lead_names = tuple(
                STANDARD_ECG_LEAD_NAMES
            )

        unusable_names = set(
            unusable_names
        )

        return tuple(
            SimpleNamespace(
                name=lead_name,
                usable=(
                    lead_name
                    not in unusable_names
                ),
                coverage_ratio=(
                    0.95
                    if lead_name
                    not in unusable_names
                    else 0.25
                ),
                quality_level=(
                    "high"
                    if lead_name
                    not in unusable_names
                    else "insufficient"
                ),
            )
            for lead_name in lead_names
        )

    def _build_pipeline_result(
        self,
        *,
        extraction_present=True,
        extraction_complete=True,
        quality_present=True,
        quality_complete=True,
        all_usable=True,
        grid_present=True,
        calibrated_signal_present=True,
        extraction_lead_names=None,
        quality_lead_names=None,
        unusable_names=(),
        pixels_per_mm=8.0,
        paper_speed_mm_per_s=25.0,
        gain_mm_per_mv=10.0,
    ):
        """
        Build a lightweight object exposing the attributes consumed
        by build_ecg_ai_input().
        """

        if extraction_lead_names is None:
            extraction_lead_names = tuple(
                STANDARD_ECG_LEAD_NAMES
            )

        if quality_lead_names is None:
            quality_lead_names = tuple(
                STANDARD_ECG_LEAD_NAMES
            )

        extraction = None

        if extraction_present:
            extracted_leads = (
                self._build_extracted_leads(
                    lead_names=(
                        extraction_lead_names
                    ),
                )
            )

            extraction = SimpleNamespace(
                layout_format="standard_3x4",
                source_width=1600,
                source_height=1200,
                leads=extracted_leads,
                lead_names=tuple(
                    lead.name
                    for lead in extracted_leads
                ),
                complete_12_lead=(
                    extraction_complete
                ),
            )

        quality_assessment = None

        if quality_present:
            quality_leads = (
                self._build_quality_leads(
                    lead_names=(
                        quality_lead_names
                    ),
                    unusable_names=(
                        unusable_names
                    ),
                )
            )

            quality_assessment = (
                SimpleNamespace(
                    layout_format=(
                        "standard_3x4"
                    ),
                    leads=quality_leads,
                    lead_names=tuple(
                        lead.name
                        for lead in quality_leads
                    ),
                    complete_12_lead=(
                        quality_complete
                    ),
                    all_usable=(
                        all_usable
                    ),
                )
            )

        grid_detection = None

        if grid_present:
            grid_detection = (
                SimpleNamespace(
                    pixels_per_mm=(
                        pixels_per_mm
                    ),
                )
            )

        calibrated_signal = None

        if calibrated_signal_present:
            calibrated_signal = (
                SimpleNamespace(
                    parameters=(
                        ECGCalibrationParameters(
                            pixels_per_mm=(
                                pixels_per_mm
                            ),
                            paper_speed_mm_per_s=(
                                paper_speed_mm_per_s
                            ),
                            gain_mm_per_mv=(
                                gain_mm_per_mv
                            ),
                        )
                    )
                )
            )

        return SimpleNamespace(
            lead_signal_extraction=(
                extraction
            ),
            lead_quality_assessment=(
                quality_assessment
            ),
            grid_detection=(
                grid_detection
            ),
            calibrated_signal=(
                calibrated_signal
            ),
        )

    def _successful_calibration_result(
        self,
        reconstructed_signal,
        *,
        pixels_per_mm,
        paper_speed_mm_per_s,
        gain_mm_per_mv,
    ):
        """
        Return deterministic calibrated data for one lead.

        Missing samples intentionally remain None.
        """

        parameters = ECGCalibrationParameters(
            pixels_per_mm=(
                float(
                    pixels_per_mm
                )
            ),
            paper_speed_mm_per_s=(
                float(
                    paper_speed_mm_per_s
                )
            ),
            gain_mm_per_mv=(
                float(
                    gain_mm_per_mv
                )
            ),
        )

        return SimpleNamespace(
            time_seconds=(
                0.0,
                0.04,
                0.08,
            ),
            amplitude_mv=(
                0.10,
                None,
                -0.20,
            ),
            parameters=parameters,
        )

    # =====================================================
    # Required Pipeline Components
    # =====================================================

    def test_none_pipeline_result_is_rejected(
        self,
    ):
        with self.assertRaisesRegex(
            ECGAIInputError,
            "pipeline result is required",
        ):
            build_ecg_ai_input(
                None
            )

    def test_missing_lead_extraction_is_rejected(
        self,
    ):
        pipeline_result = (
            self._build_pipeline_result(
                extraction_present=False,
            )
        )

        with self.assertRaisesRegex(
            ECGAIInputError,
            "independently extracted",
        ):
            build_ecg_ai_input(
                pipeline_result
            )

    def test_incomplete_twelve_lead_extraction_is_rejected(
        self,
    ):
        pipeline_result = (
            self._build_pipeline_result(
                extraction_complete=False,
            )
        )

        with self.assertRaisesRegex(
            ECGAIInputError,
            "complete set of twelve",
        ):
            build_ecg_ai_input(
                pipeline_result
            )

    def test_missing_per_lead_quality_assessment_is_rejected(
        self,
    ):
        pipeline_result = (
            self._build_pipeline_result(
                quality_present=False,
            )
        )

        with self.assertRaisesRegex(
            ECGAIInputError,
            "per-lead ECG processing-quality",
        ):
            build_ecg_ai_input(
                pipeline_result
            )

    def test_incomplete_quality_assessment_is_rejected(
        self,
    ):
        pipeline_result = (
            self._build_pipeline_result(
                quality_complete=False,
            )
        )

        with self.assertRaisesRegex(
            ECGAIInputError,
            "quality results",
        ):
            build_ecg_ai_input(
                pipeline_result
            )

    # =====================================================
    # Quality Gate
    # =====================================================

    def test_unusable_lead_is_rejected_and_named(
        self,
    ):
        pipeline_result = (
            self._build_pipeline_result(
                all_usable=False,
                unusable_names=(
                    "V6",
                ),
            )
        )

        with self.assertRaisesRegex(
            ECGAIInputError,
            "V6",
        ):
            build_ecg_ai_input(
                pipeline_result
            )

    # =====================================================
    # Calibration Context
    # =====================================================

    def test_missing_grid_detection_is_rejected(
        self,
    ):
        pipeline_result = (
            self._build_pipeline_result(
                grid_present=False,
            )
        )

        with self.assertRaisesRegex(
            ECGAIInputError,
            "grid detection",
        ):
            build_ecg_ai_input(
                pipeline_result
            )

    def test_missing_pipeline_calibration_is_rejected(
        self,
    ):
        pipeline_result = (
            self._build_pipeline_result(
                calibrated_signal_present=False,
            )
        )

        with self.assertRaisesRegex(
            ECGAIInputError,
            "signal calibration",
        ):
            build_ecg_ai_input(
                pipeline_result
            )

    def test_non_positive_grid_scale_is_rejected(
        self,
    ):
        pipeline_result = (
            self._build_pipeline_result(
                pixels_per_mm=0.0,
            )
        )

        with self.assertRaisesRegex(
            ECGAIInputError,
            "must be positive",
        ):
            build_ecg_ai_input(
                pipeline_result
            )

    # =====================================================
    # Extraction / Quality Alignment
    # =====================================================

    def test_different_extraction_and_quality_lead_sets_are_rejected(
        self,
    ):
        quality_names = list(
            STANDARD_ECG_LEAD_NAMES
        )

        quality_names[-1] = (
            "UNKNOWN"
        )

        pipeline_result = (
            self._build_pipeline_result(
                quality_lead_names=tuple(
                    quality_names
                ),
            )
        )

        with self.assertRaisesRegex(
            ECGAIInputError,
            "do not describe the same set",
        ):
            build_ecg_ai_input(
                pipeline_result
            )

    # =====================================================
    # Successful Contract Construction
    # =====================================================

    @patch(
        "ecg.services.ai.input_contract."
        "calibrate_reconstructed_signal"
    )
    def test_builds_complete_ai_input_in_canonical_lead_order(
        self,
        mock_calibrate,
    ):
        """
        Even when extraction arrives in a different order, the
        resulting AI contract must use the project's canonical
        twelve-lead order.
        """

        reversed_names = tuple(
            reversed(
                STANDARD_ECG_LEAD_NAMES
            )
        )

        pipeline_result = (
            self._build_pipeline_result(
                extraction_lead_names=(
                    reversed_names
                ),
                quality_lead_names=(
                    reversed_names
                ),
            )
        )

        mock_calibrate.side_effect = (
            self._successful_calibration_result
        )

        result = build_ecg_ai_input(
            pipeline_result
        )

        self.assertTrue(
            result.complete_12_lead
        )

        self.assertEqual(
            result.lead_count,
            12,
        )

        self.assertEqual(
            result.lead_names,
            tuple(
                STANDARD_ECG_LEAD_NAMES
            ),
        )

        self.assertEqual(
            result.layout_format,
            "standard_3x4",
        )

        self.assertEqual(
            result.source_width,
            1600,
        )

        self.assertEqual(
            result.source_height,
            1200,
        )

        self.assertEqual(
            result.pixels_per_mm,
            8.0,
        )

        self.assertEqual(
            result.paper_speed_mm_per_s,
            25.0,
        )

        self.assertEqual(
            result.gain_mm_per_mv,
            10.0,
        )

        self.assertEqual(
            mock_calibrate.call_count,
            12,
        )

    @patch(
        "ecg.services.ai.input_contract."
        "calibrate_reconstructed_signal"
    )
    def test_each_named_lead_uses_existing_calibration_context(
        self,
        mock_calibrate,
    ):
        pipeline_result = (
            self._build_pipeline_result(
                pixels_per_mm=9.5,
                paper_speed_mm_per_s=25.0,
                gain_mm_per_mv=10.0,
            )
        )

        mock_calibrate.side_effect = (
            self._successful_calibration_result
        )

        build_ecg_ai_input(
            pipeline_result
        )

        self.assertEqual(
            mock_calibrate.call_count,
            12,
        )

        for call in mock_calibrate.call_args_list:
            self.assertEqual(
                call.kwargs[
                    "pixels_per_mm"
                ],
                9.5,
            )

            self.assertEqual(
                call.kwargs[
                    "paper_speed_mm_per_s"
                ],
                25.0,
            )

            self.assertEqual(
                call.kwargs[
                    "gain_mm_per_mv"
                ],
                10.0,
            )

    @patch(
        "ecg.services.ai.input_contract."
        "calibrate_reconstructed_signal"
    )
    def test_calibrated_time_and_amplitude_are_preserved(
        self,
        mock_calibrate,
    ):
        pipeline_result = (
            self._build_pipeline_result()
        )

        mock_calibrate.side_effect = (
            self._successful_calibration_result
        )

        result = build_ecg_ai_input(
            pipeline_result
        )

        lead = result.leads[0]

        self.assertEqual(
            lead.time_seconds,
            (
                0.0,
                0.04,
                0.08,
            ),
        )

        self.assertEqual(
            lead.amplitude_mv,
            (
                0.10,
                None,
                -0.20,
            ),
        )

        self.assertEqual(
            lead.total_sample_count,
            3,
        )

        self.assertEqual(
            lead.available_sample_count,
            2,
        )

        self.assertEqual(
            lead.missing_sample_count,
            1,
        )

        self.assertAlmostEqual(
            lead.duration_seconds,
            0.08,
        )

    @patch(
        "ecg.services.ai.input_contract."
        "calibrate_reconstructed_signal"
    )
    def test_quality_metadata_is_preserved_for_each_lead(
        self,
        mock_calibrate,
    ):
        pipeline_result = (
            self._build_pipeline_result()
        )

        mock_calibrate.side_effect = (
            self._successful_calibration_result
        )

        result = build_ecg_ai_input(
            pipeline_result
        )

        for lead in result.leads:
            self.assertEqual(
                lead.coverage_ratio,
                0.95,
            )

            self.assertEqual(
                lead.quality_level,
                "high",
            )

    # =====================================================
    # Calibration Failure Safety
    # =====================================================

    @patch(
        "ecg.services.ai.input_contract."
        "calibrate_reconstructed_signal"
    )
    def test_calibration_failure_is_wrapped_as_ai_input_error(
        self,
        mock_calibrate,
    ):
        pipeline_result = (
            self._build_pipeline_result()
        )

        mock_calibrate.side_effect = (
            ECGCalibrationError(
                "Synthetic calibration failure."
            )
        )

        first_lead_name = (
            STANDARD_ECG_LEAD_NAMES[0]
        )

        with self.assertRaisesRegex(
            ECGAIInputError,
            first_lead_name,
        ):
            build_ecg_ai_input(
                pipeline_result
            )

    @patch(
        "ecg.services.ai.input_contract."
        "calibrate_reconstructed_signal"
    )
    def test_inconsistent_time_and_amplitude_lengths_are_rejected(
        self,
        mock_calibrate,
    ):
        pipeline_result = (
            self._build_pipeline_result()
        )

        parameters = (
            ECGCalibrationParameters(
                pixels_per_mm=8.0,
                paper_speed_mm_per_s=25.0,
                gain_mm_per_mv=10.0,
            )
        )

        mock_calibrate.return_value = (
            SimpleNamespace(
                time_seconds=(
                    0.0,
                    0.04,
                ),
                amplitude_mv=(
                    0.10,
                ),
                parameters=parameters,
            )
        )

        with self.assertRaisesRegex(
            ECGAIInputError,
            "inconsistent time",
        ):
            build_ecg_ai_input(
                pipeline_result
            )

    @patch(
        "ecg.services.ai.input_contract."
        "calibrate_reconstructed_signal"
    )
    def test_inconsistent_calibration_parameters_across_leads_are_rejected(
        self,
        mock_calibrate,
    ):
        pipeline_result = (
            self._build_pipeline_result()
        )

        normal_parameters = (
            ECGCalibrationParameters(
                pixels_per_mm=8.0,
                paper_speed_mm_per_s=25.0,
                gain_mm_per_mv=10.0,
            )
        )

        different_parameters = (
            ECGCalibrationParameters(
                pixels_per_mm=8.0,
                paper_speed_mm_per_s=50.0,
                gain_mm_per_mv=10.0,
            )
        )

        call_number = 0

        def calibration_side_effect(
            reconstructed_signal,
            *,
            pixels_per_mm,
            paper_speed_mm_per_s,
            gain_mm_per_mv,
        ):
            nonlocal call_number

            call_number += 1

            parameters = (
                different_parameters
                if call_number == 2
                else normal_parameters
            )

            return SimpleNamespace(
                time_seconds=(
                    0.0,
                    0.04,
                    0.08,
                ),
                amplitude_mv=(
                    0.10,
                    0.00,
                    -0.20,
                ),
                parameters=parameters,
            )

        mock_calibrate.side_effect = (
            calibration_side_effect
        )

        with self.assertRaisesRegex(
            ECGAIInputError,
            "consistent calibration",
        ):
            build_ecg_ai_input(
                pipeline_result
            )