"""
Tests for ECG AI model preprocessing.

These tests verify the layer that converts calibrated twelve-lead ECG
signals into fixed-shape model input.

Covered behavior:
    - Explicit preprocessing configuration validation.
    - Canonical twelve-lead preservation.
    - Fixed target sampling frequency and sample count.
    - Explicit twelve-lead temporal-layout preservation.
    - Linear resampling.
    - Missing-data rejection.
    - Controlled internal interpolation.
    - Prevention of signal extrapolation.
    - Per-lead z-score normalization.
    - Fixed-shape finite ECGPreparedModelInput output.

No trained ECG model is loaded.
No clinical prediction or diagnosis is performed.
"""

import math

import numpy as np
from django.test import SimpleTestCase

from ecg.services.ai.input_contract import (
    ECGAIInput,
    ECGAILeadInput,
)
from ecg.services.ai.model_interface import (
    INPUT_TEMPORAL_LAYOUT_STANDARD_3X4_SEQUENTIAL,
    INPUT_TEMPORAL_LAYOUT_SYNCHRONOUS_12_LEAD,
)
from ecg.services.ai.preprocessing import (
    ECGPreprocessingConfig,
    ECGPreprocessingError,
    MISSING_DATA_LINEAR_INTERPOLATION,
    MISSING_DATA_REJECT,
    NORMALIZATION_NONE,
    NORMALIZATION_ZSCORE_PER_LEAD,
    prepare_ecg_model_input,
)
from ecg.services.lead_identification import (
    STANDARD_ECG_LEAD_NAMES,
)


class ECGPreprocessingTests(SimpleTestCase):
    """
    Unit tests for the ECG AI preprocessing layer.
    """

    def _build_lead(
        self,
        name,
        *,
        time_seconds=None,
        amplitude_mv=None,
        coverage_ratio=1.0,
        quality_level="high",
    ):
        if time_seconds is None:
            time_seconds = (
                0.0,
                0.5,
                1.0,
                1.5,
                2.0,
            )

        if amplitude_mv is None:
            amplitude_mv = (
                0.0,
                1.0,
                2.0,
                3.0,
                4.0,
            )

        return ECGAILeadInput(
            name=name,
            time_seconds=tuple(
                time_seconds
            ),
            amplitude_mv=tuple(
                amplitude_mv
            ),
            coverage_ratio=float(
                coverage_ratio
            ),
            quality_level=quality_level,
        )

    def _build_ai_input(
        self,
        *,
        time_seconds=None,
        amplitude_mv=None,
        lead_overrides=None,
    ):
        """
        Build a canonical twelve-lead ECGAIInput fixture.
        """

        if lead_overrides is None:
            lead_overrides = {}

        leads = []

        for lead_name in STANDARD_ECG_LEAD_NAMES:
            overrides = lead_overrides.get(
                lead_name,
                {},
            )

            lead = self._build_lead(
                lead_name,
                time_seconds=overrides.get(
                    "time_seconds",
                    time_seconds,
                ),
                amplitude_mv=overrides.get(
                    "amplitude_mv",
                    amplitude_mv,
                ),
                coverage_ratio=overrides.get(
                    "coverage_ratio",
                    1.0,
                ),
                quality_level=overrides.get(
                    "quality_level",
                    "high",
                ),
            )

            leads.append(
                lead
            )

        return ECGAIInput(
            layout_format="standard_3x4",
            source_width=1600,
            source_height=1200,
            pixels_per_mm=8.0,
            paper_speed_mm_per_s=25.0,
            gain_mm_per_mv=10.0,
            leads=tuple(
                leads
            ),
        )

    def _build_config(
        self,
        **overrides,
    ):
        values = {
            "target_sampling_frequency_hz": 2.0,
            "target_sample_count": 5,
            "preprocessing_version": (
                "ecg-preprocess-v1"
            ),
            "input_temporal_layout": (
                INPUT_TEMPORAL_LAYOUT_SYNCHRONOUS_12_LEAD
            ),
            "normalization_method": (
                NORMALIZATION_NONE
            ),
            "missing_data_method": (
                MISSING_DATA_REJECT
            ),
            "max_missing_fraction_per_lead": 0.0,
            "max_interpolation_gap_seconds": None,
            "window_start_seconds": 0.0,
        }

        values.update(
            overrides
        )

        return ECGPreprocessingConfig(
            **values
        )

    # =====================================================
    # Configuration Validation
    # =====================================================

    def test_valid_config_exposes_expected_duration(
        self,
    ):
        config = self._build_config()

        self.assertAlmostEqual(
            config.target_duration_seconds,
            2.0,
        )

        self.assertAlmostEqual(
            config.window_end_seconds,
            2.0,
        )

        self.assertEqual(
            config.input_temporal_layout,
            INPUT_TEMPORAL_LAYOUT_SYNCHRONOUS_12_LEAD,
        )

    def test_zero_sampling_frequency_is_rejected(
        self,
    ):
        with self.assertRaisesRegex(
            ECGPreprocessingError,
            "positive finite number",
        ):
            self._build_config(
                target_sampling_frequency_hz=0,
            )

    def test_non_finite_sampling_frequency_is_rejected(
        self,
    ):
        with self.assertRaisesRegex(
            ECGPreprocessingError,
            "positive finite number",
        ):
            self._build_config(
                target_sampling_frequency_hz=math.inf,
            )

    def test_target_sample_count_must_exceed_one(
        self,
    ):
        with self.assertRaisesRegex(
            ECGPreprocessingError,
            "greater than one",
        ):
            self._build_config(
                target_sample_count=1,
            )

    def test_boolean_sample_count_is_rejected(
        self,
    ):
        with self.assertRaisesRegex(
            ECGPreprocessingError,
            "greater than one",
        ):
            self._build_config(
                target_sample_count=True,
            )

    def test_blank_preprocessing_version_is_rejected(
        self,
    ):
        with self.assertRaisesRegex(
            ECGPreprocessingError,
            "version is required",
        ):
            self._build_config(
                preprocessing_version="",
            )

    def test_blank_input_temporal_layout_is_rejected(
        self,
    ):
        with self.assertRaisesRegex(
            ECGPreprocessingError,
            "temporal layout is required",
        ):
            self._build_config(
                input_temporal_layout="",
            )

    def test_unsupported_input_temporal_layout_is_rejected(
        self,
    ):
        with self.assertRaisesRegex(
            ECGPreprocessingError,
            "Unsupported ECG input temporal layout",
        ):
            self._build_config(
                input_temporal_layout="unsupported",
            )

    def test_unsupported_normalization_method_is_rejected(
        self,
    ):
        with self.assertRaisesRegex(
            ECGPreprocessingError,
            "Unsupported ECG normalization",
        ):
            self._build_config(
                normalization_method="unknown",
            )

    def test_unsupported_missing_data_method_is_rejected(
        self,
    ):
        with self.assertRaisesRegex(
            ECGPreprocessingError,
            "Unsupported ECG missing-data",
        ):
            self._build_config(
                missing_data_method="unknown",
            )

    def test_missing_fraction_above_one_is_rejected(
        self,
    ):
        with self.assertRaisesRegex(
            ECGPreprocessingError,
            "between 0 and 1",
        ):
            self._build_config(
                max_missing_fraction_per_lead=1.1,
            )

    def test_reject_policy_requires_zero_missing_fraction(
        self,
    ):
        with self.assertRaisesRegex(
            ECGPreprocessingError,
            "must be zero",
        ):
            self._build_config(
                missing_data_method=(
                    MISSING_DATA_REJECT
                ),
                max_missing_fraction_per_lead=0.1,
            )

    def test_linear_interpolation_requires_explicit_gap_limit(
        self,
    ):
        with self.assertRaisesRegex(
            ECGPreprocessingError,
            "explicit maximum interpolation gap",
        ):
            self._build_config(
                missing_data_method=(
                    MISSING_DATA_LINEAR_INTERPOLATION
                ),
                max_missing_fraction_per_lead=0.25,
                max_interpolation_gap_seconds=None,
            )

    def test_linear_interpolation_gap_limit_must_be_positive(
        self,
    ):
        with self.assertRaisesRegex(
            ECGPreprocessingError,
            "positive finite number",
        ):
            self._build_config(
                missing_data_method=(
                    MISSING_DATA_LINEAR_INTERPOLATION
                ),
                max_missing_fraction_per_lead=0.25,
                max_interpolation_gap_seconds=0,
            )

    def test_negative_window_start_is_rejected(
        self,
    ):
        with self.assertRaisesRegex(
            ECGPreprocessingError,
            "non-negative finite",
        ):
            self._build_config(
                window_start_seconds=-0.1,
            )

    # =====================================================
    # Basic Model Preparation
    # =====================================================

    def test_prepare_requires_ai_input_instance(
        self,
    ):
        config = self._build_config()

        with self.assertRaisesRegex(
            ECGPreprocessingError,
            "ECGAIInput instance",
        ):
            prepare_ecg_model_input(
                object(),
                config,
            )

    def test_prepare_requires_config_instance(
        self,
    ):
        ai_input = self._build_ai_input()

        with self.assertRaisesRegex(
            ECGPreprocessingError,
            "ECGPreprocessingConfig",
        ):
            prepare_ecg_model_input(
                ai_input,
                object(),
            )

    def test_prepares_fixed_shape_canonical_input(
        self,
    ):
        ai_input = self._build_ai_input()

        config = self._build_config()

        result = prepare_ecg_model_input(
            ai_input,
            config,
        )

        self.assertEqual(
            result.shape,
            (
                12,
                5,
            ),
        )

        self.assertEqual(
            result.lead_names,
            tuple(
                STANDARD_ECG_LEAD_NAMES
            ),
        )

        self.assertEqual(
            result.sampling_frequency_hz,
            2.0,
        )

        self.assertEqual(
            result.preprocessing_version,
            "ecg-preprocess-v1",
        )

        self.assertEqual(
            result.normalization_method,
            NORMALIZATION_NONE,
        )

        self.assertEqual(
            result.input_temporal_layout,
            INPUT_TEMPORAL_LAYOUT_SYNCHRONOUS_12_LEAD,
        )

        self.assertFalse(
            result.uses_sequential_print_layout
        )

    def test_sequential_temporal_layout_is_preserved_in_prepared_input(
        self,
    ):
        ai_input = self._build_ai_input()

        config = self._build_config(
            input_temporal_layout=(
                INPUT_TEMPORAL_LAYOUT_STANDARD_3X4_SEQUENTIAL
            ),
        )

        result = prepare_ecg_model_input(
            ai_input,
            config,
        )

        self.assertEqual(
            result.input_temporal_layout,
            INPUT_TEMPORAL_LAYOUT_STANDARD_3X4_SEQUENTIAL,
        )

        self.assertTrue(
            result.uses_sequential_print_layout
        )

    # =====================================================
    # Resampling
    # =====================================================

    def test_linear_resampling_produces_expected_values(
        self,
    ):
        ai_input = self._build_ai_input(
            time_seconds=(
                0.0,
                1.0,
                2.0,
            ),
            amplitude_mv=(
                0.0,
                2.0,
                4.0,
            ),
        )

        config = self._build_config(
            target_sampling_frequency_hz=2.0,
            target_sample_count=5,
        )

        result = prepare_ecg_model_input(
            ai_input,
            config,
        )

        expected = (
            0.0,
            1.0,
            2.0,
            3.0,
            4.0,
        )

        for lead_samples in result.samples:
            np.testing.assert_allclose(
                lead_samples,
                expected,
                rtol=0,
                atol=1e-12,
            )

    def test_window_start_selects_later_signal_region(
        self,
    ):
        ai_input = self._build_ai_input(
            time_seconds=(
                0.0,
                1.0,
                2.0,
                3.0,
            ),
            amplitude_mv=(
                0.0,
                10.0,
                20.0,
                30.0,
            ),
        )

        config = self._build_config(
            target_sampling_frequency_hz=1.0,
            target_sample_count=3,
            window_start_seconds=1.0,
        )

        result = prepare_ecg_model_input(
            ai_input,
            config,
        )

        expected = (
            10.0,
            20.0,
            30.0,
        )

        np.testing.assert_allclose(
            result.samples[0],
            expected,
            rtol=0,
            atol=1e-12,
        )

    def test_source_shorter_than_target_window_is_rejected(
        self,
    ):
        ai_input = self._build_ai_input(
            time_seconds=(
                0.0,
                0.5,
                1.0,
            ),
            amplitude_mv=(
                0.0,
                1.0,
                2.0,
            ),
        )

        config = self._build_config(
            target_sampling_frequency_hz=2.0,
            target_sample_count=5,
        )

        with self.assertRaisesRegex(
            ECGPreprocessingError,
            "shorter than the requested",
        ):
            prepare_ecg_model_input(
                ai_input,
                config,
            )

    def test_source_starting_after_requested_window_is_rejected(
        self,
    ):
        ai_input = self._build_ai_input(
            time_seconds=(
                0.5,
                1.0,
                1.5,
                2.0,
                2.5,
            ),
            amplitude_mv=(
                0.0,
                1.0,
                2.0,
                3.0,
                4.0,
            ),
        )

        config = self._build_config(
            target_sampling_frequency_hz=2.0,
            target_sample_count=5,
            window_start_seconds=0.0,
        )

        with self.assertRaisesRegex(
            ECGPreprocessingError,
            "beginning of the requested",
        ):
            prepare_ecg_model_input(
                ai_input,
                config,
            )

    # =====================================================
    # Lead Signal Validation
    # =====================================================

    def test_non_increasing_time_values_are_rejected(
        self,
    ):
        ai_input = self._build_ai_input(
            lead_overrides={
                "I": {
                    "time_seconds": (
                        0.0,
                        0.5,
                        0.5,
                        1.5,
                        2.0,
                    ),
                },
            },
        )

        config = self._build_config()

        with self.assertRaisesRegex(
            ECGPreprocessingError,
            "strictly increasing",
        ):
            prepare_ecg_model_input(
                ai_input,
                config,
            )

    def test_inconsistent_time_and_amplitude_lengths_are_rejected(
        self,
    ):
        ai_input = self._build_ai_input(
            lead_overrides={
                "I": {
                    "time_seconds": (
                        0.0,
                        0.5,
                        1.0,
                    ),
                    "amplitude_mv": (
                        0.0,
                        1.0,
                    ),
                },
            },
        )

        config = self._build_config()

        with self.assertRaisesRegex(
            ECGPreprocessingError,
            "inconsistent time and amplitude",
        ):
            prepare_ecg_model_input(
                ai_input,
                config,
            )

    def test_non_finite_amplitude_is_rejected(
        self,
    ):
        ai_input = self._build_ai_input(
            lead_overrides={
                "I": {
                    "amplitude_mv": (
                        0.0,
                        1.0,
                        math.inf,
                        3.0,
                        4.0,
                    ),
                },
            },
        )

        config = self._build_config()

        with self.assertRaisesRegex(
            ECGPreprocessingError,
            "non-finite amplitude",
        ):
            prepare_ecg_model_input(
                ai_input,
                config,
            )

    # =====================================================
    # Missing Data Policy
    # =====================================================

    def test_reject_policy_rejects_any_missing_sample(
        self,
    ):
        ai_input = self._build_ai_input(
            lead_overrides={
                "I": {
                    "amplitude_mv": (
                        0.0,
                        1.0,
                        None,
                        3.0,
                        4.0,
                    ),
                },
            },
        )

        config = self._build_config(
            missing_data_method=(
                MISSING_DATA_REJECT
            ),
        )

        with self.assertRaisesRegex(
            ECGPreprocessingError,
            "rejects missing data",
        ):
            prepare_ecg_model_input(
                ai_input,
                config,
            )

    def test_internal_missing_sample_can_be_interpolated(
        self,
    ):
        ai_input = self._build_ai_input(
            lead_overrides={
                "I": {
                    "time_seconds": (
                        0.0,
                        0.5,
                        1.0,
                        1.5,
                        2.0,
                    ),
                    "amplitude_mv": (
                        0.0,
                        1.0,
                        None,
                        3.0,
                        4.0,
                    ),
                },
            },
        )

        config = self._build_config(
            missing_data_method=(
                MISSING_DATA_LINEAR_INTERPOLATION
            ),
            max_missing_fraction_per_lead=0.25,
            max_interpolation_gap_seconds=1.0,
        )

        result = prepare_ecg_model_input(
            ai_input,
            config,
        )

        self.assertEqual(
            result.samples[0],
            (
                0.0,
                1.0,
                2.0,
                3.0,
                4.0,
            ),
        )

    def test_missing_fraction_limit_is_enforced(
        self,
    ):
        ai_input = self._build_ai_input(
            lead_overrides={
                "I": {
                    "amplitude_mv": (
                        0.0,
                        None,
                        None,
                        3.0,
                        4.0,
                    ),
                },
            },
        )

        config = self._build_config(
            missing_data_method=(
                MISSING_DATA_LINEAR_INTERPOLATION
            ),
            max_missing_fraction_per_lead=0.20,
            max_interpolation_gap_seconds=2.0,
        )

        with self.assertRaisesRegex(
            ECGPreprocessingError,
            "maximum missing-sample fraction",
        ):
            prepare_ecg_model_input(
                ai_input,
                config,
            )

    def test_missing_gap_limit_is_enforced(
        self,
    ):
        ai_input = self._build_ai_input(
            lead_overrides={
                "I": {
                    "time_seconds": (
                        0.0,
                        0.5,
                        1.0,
                        1.5,
                        2.0,
                    ),
                    "amplitude_mv": (
                        0.0,
                        1.0,
                        None,
                        3.0,
                        4.0,
                    ),
                },
            },
        )

        config = self._build_config(
            missing_data_method=(
                MISSING_DATA_LINEAR_INTERPOLATION
            ),
            max_missing_fraction_per_lead=0.25,
            max_interpolation_gap_seconds=0.5,
        )

        with self.assertRaisesRegex(
            ECGPreprocessingError,
            "larger than the configured",
        ):
            prepare_ecg_model_input(
                ai_input,
                config,
            )

    def test_missing_sample_at_signal_start_is_rejected(
        self,
    ):
        ai_input = self._build_ai_input(
            lead_overrides={
                "I": {
                    "amplitude_mv": (
                        None,
                        1.0,
                        2.0,
                        3.0,
                        4.0,
                    ),
                },
            },
        )

        config = self._build_config(
            missing_data_method=(
                MISSING_DATA_LINEAR_INTERPOLATION
            ),
            max_missing_fraction_per_lead=0.25,
            max_interpolation_gap_seconds=1.0,
        )

        with self.assertRaisesRegex(
            ECGPreprocessingError,
            "extrapolation is not allowed",
        ):
            prepare_ecg_model_input(
                ai_input,
                config,
            )

    def test_missing_sample_at_signal_end_is_rejected(
        self,
    ):
        ai_input = self._build_ai_input(
            lead_overrides={
                "I": {
                    "amplitude_mv": (
                        0.0,
                        1.0,
                        2.0,
                        3.0,
                        None,
                    ),
                },
            },
        )

        config = self._build_config(
            missing_data_method=(
                MISSING_DATA_LINEAR_INTERPOLATION
            ),
            max_missing_fraction_per_lead=0.25,
            max_interpolation_gap_seconds=1.0,
        )

        with self.assertRaisesRegex(
            ECGPreprocessingError,
            "extrapolation is not allowed",
        ):
            prepare_ecg_model_input(
                ai_input,
                config,
            )

    # =====================================================
    # Normalization
    # =====================================================

    def test_zscore_normalization_produces_zero_mean_unit_variance(
        self,
    ):
        ai_input = self._build_ai_input(
            amplitude_mv=(
                1.0,
                2.0,
                3.0,
                4.0,
                5.0,
            ),
        )

        config = self._build_config(
            normalization_method=(
                NORMALIZATION_ZSCORE_PER_LEAD
            ),
        )

        result = prepare_ecg_model_input(
            ai_input,
            config,
        )

        for lead_samples in result.samples:
            values = np.asarray(
                lead_samples,
                dtype=np.float64,
            )

            self.assertAlmostEqual(
                float(
                    np.mean(
                        values
                    )
                ),
                0.0,
                places=12,
            )

            self.assertAlmostEqual(
                float(
                    np.std(
                        values,
                        ddof=0,
                    )
                ),
                1.0,
                places=12,
            )

    def test_constant_signal_cannot_be_zscore_normalized(
        self,
    ):
        ai_input = self._build_ai_input(
            amplitude_mv=(
                2.0,
                2.0,
                2.0,
                2.0,
                2.0,
            ),
        )

        config = self._build_config(
            normalization_method=(
                NORMALIZATION_ZSCORE_PER_LEAD
            ),
        )

        with self.assertRaisesRegex(
            ECGPreprocessingError,
            "standard deviation",
        ):
            prepare_ecg_model_input(
                ai_input,
                config,
            )

    def test_none_normalization_preserves_resampled_values(
        self,
    ):
        ai_input = self._build_ai_input()

        config = self._build_config(
            normalization_method=(
                NORMALIZATION_NONE
            ),
        )

        result = prepare_ecg_model_input(
            ai_input,
            config,
        )

        expected = (
            0.0,
            1.0,
            2.0,
            3.0,
            4.0,
        )

        self.assertEqual(
            result.samples[0],
            expected,
        )