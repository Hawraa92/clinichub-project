"""
Tests for the ECG AI model specification contract.

These tests verify that one explicit model specification can act as
the authoritative source for:

    - model identity,
    - output labels,
    - decision thresholds,
    - input sampling requirements,
    - preprocessing requirements,
    - temporal relationships between twelve ECG leads,
    - synchronous twelve-lead input,
    - sequential standard 3x4 print-layout input,
    - source-recording windows used for dataset construction,
    - runtime model metadata,
    - model artifact traceability.

No trained ECG model is loaded.
No clinical diagnosis or XAI explanation is produced.
"""

from django.test import SimpleTestCase

from ecg.services.ai.model_interface import (
    ECGModelMetadata,
)
from ecg.services.ai.model_specification import (
    ECGLabelSpecification,
    ECGLeadSourceWindow,
    ECGModelSpecification,
    ECGModelSpecificationError,
    INPUT_TEMPORAL_LAYOUT_STANDARD_3X4_SEQUENTIAL,
    INPUT_TEMPORAL_LAYOUT_SYNCHRONOUS_12_LEAD,
    OUTPUT_BINARY_PROBABILITY,
    OUTPUT_MULTICLASS_PROBABILITY,
    OUTPUT_MULTILABEL_PROBABILITY,
    STANDARD_3X4_SEQUENTIAL_COLUMNS,
)
from ecg.services.ai.preprocessing import (
    ECGPreprocessingConfig,
    MISSING_DATA_LINEAR_INTERPOLATION,
    MISSING_DATA_REJECT,
    NORMALIZATION_NONE,
    NORMALIZATION_ZSCORE_PER_LEAD,
)
from ecg.services.lead_identification import (
    STANDARD_ECG_LEAD_NAMES,
)


class ECGModelSpecificationTests(SimpleTestCase):
    """
    Unit tests for the reproducible ECG model specification.
    """

    def _valid_labels(
        self,
    ):
        return (
            ECGLabelSpecification(
                name="class_a",
                display_name="Class A",
                decision_threshold=0.40,
            ),
            ECGLabelSpecification(
                name="class_b",
                display_name="Class B",
                decision_threshold=0.65,
            ),
        )

    def _valid_specification(
        self,
        **overrides,
    ):
        """
        Build a valid synchronous twelve-lead specification.

        Values are deliberately synthetic and are used only for
        contract tests.
        """

        values = {
            "model_name": "synthetic_ecg_model",
            "model_version": "1.0.0",
            "task": "synthetic_multilabel_ecg_task",
            "framework": "test",
            "labels": self._valid_labels(),
            "output_semantics": (
                OUTPUT_MULTILABEL_PROBABILITY
            ),
            "input_sampling_frequency_hz": 2.0,
            "input_sample_count": 5,
            "input_temporal_layout": (
                INPUT_TEMPORAL_LAYOUT_SYNCHRONOUS_12_LEAD
            ),
            "source_column_duration_seconds": None,
            "preprocessing_version": (
                "ecg-preprocess-v1"
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
            "artifact_sha256": "",
            "description": (
                "Synthetic specification used only for tests."
            ),
        }

        values.update(
            overrides
        )

        return ECGModelSpecification(
            **values
        )

    def _valid_sequential_specification(
        self,
        **overrides,
    ):
        """
        Build a valid standard 3x4 sequential specification.

        At 2 Hz with 5 samples, each model lead consumes an
        exclusive 2.5-second source window.

        A 2.5-second source-column duration therefore makes the
        four sequential columns span 10 seconds in these synthetic
        tests.

        These values are test fixtures only. They are not clinical
        or production model defaults.
        """

        values = {
            "input_temporal_layout": (
                INPUT_TEMPORAL_LAYOUT_STANDARD_3X4_SEQUENTIAL
            ),
            "source_column_duration_seconds": 2.5,
        }

        values.update(
            overrides
        )

        return self._valid_specification(
            **values
        )

    # =====================================================
    # Label Specification
    # =====================================================

    def test_valid_label_specification_is_created(
        self,
    ):
        label = ECGLabelSpecification(
            name="class_a",
            display_name="Class A",
            decision_threshold=0.50,
        )

        self.assertEqual(
            label.name,
            "class_a",
        )

        self.assertEqual(
            label.display_name,
            "Class A",
        )

        self.assertEqual(
            label.decision_threshold,
            0.50,
        )

    def test_blank_label_name_is_rejected(
        self,
    ):
        with self.assertRaisesRegex(
            ECGModelSpecificationError,
            "label name",
        ):
            ECGLabelSpecification(
                name="",
            )

    def test_whitespace_only_display_name_is_rejected(
        self,
    ):
        with self.assertRaisesRegex(
            ECGModelSpecificationError,
            "display name",
        ):
            ECGLabelSpecification(
                name="class_a",
                display_name="   ",
            )

    def test_non_numeric_threshold_is_rejected(
        self,
    ):
        with self.assertRaisesRegex(
            ECGModelSpecificationError,
            "threshold must be numeric",
        ):
            ECGLabelSpecification(
                name="class_a",
                decision_threshold="invalid",
            )

    def test_threshold_below_zero_is_rejected(
        self,
    ):
        with self.assertRaisesRegex(
            ECGModelSpecificationError,
            "between 0 and 1",
        ):
            ECGLabelSpecification(
                name="class_a",
                decision_threshold=-0.01,
            )

    def test_threshold_above_one_is_rejected(
        self,
    ):
        with self.assertRaisesRegex(
            ECGModelSpecificationError,
            "between 0 and 1",
        ):
            ECGLabelSpecification(
                name="class_a",
                decision_threshold=1.01,
            )

    # =====================================================
    # Lead Source Window
    # =====================================================

    def test_valid_lead_source_window_is_created(
        self,
    ):
        window = ECGLeadSourceWindow(
            lead_name="I",
            temporal_segment_index=0,
            start_seconds=0.0,
            end_seconds_exclusive=2.5,
            sample_count=1250,
            sampling_frequency_hz=500.0,
        )

        self.assertEqual(
            window.lead_name,
            "I",
        )

        self.assertEqual(
            window.temporal_segment_index,
            0,
        )

        self.assertAlmostEqual(
            window.span_seconds,
            2.5,
        )

    def test_blank_source_window_lead_name_is_rejected(
        self,
    ):
        with self.assertRaisesRegex(
            ECGModelSpecificationError,
            "source-window name",
        ):
            ECGLeadSourceWindow(
                lead_name="",
                temporal_segment_index=0,
                start_seconds=0.0,
                end_seconds_exclusive=2.5,
                sample_count=5,
                sampling_frequency_hz=2.0,
            )

    def test_negative_temporal_segment_index_is_rejected(
        self,
    ):
        with self.assertRaisesRegex(
            ECGModelSpecificationError,
            "temporal segment index",
        ):
            ECGLeadSourceWindow(
                lead_name="I",
                temporal_segment_index=-1,
                start_seconds=0.0,
                end_seconds_exclusive=2.5,
                sample_count=5,
                sampling_frequency_hz=2.0,
            )

    def test_boolean_temporal_segment_index_is_rejected(
        self,
    ):
        with self.assertRaisesRegex(
            ECGModelSpecificationError,
            "temporal segment index",
        ):
            ECGLeadSourceWindow(
                lead_name="I",
                temporal_segment_index=True,
                start_seconds=0.0,
                end_seconds_exclusive=2.5,
                sample_count=5,
                sampling_frequency_hz=2.0,
            )

    def test_negative_source_window_start_is_rejected(
        self,
    ):
        with self.assertRaisesRegex(
            ECGModelSpecificationError,
            "source-window start",
        ):
            ECGLeadSourceWindow(
                lead_name="I",
                temporal_segment_index=0,
                start_seconds=-0.1,
                end_seconds_exclusive=2.5,
                sample_count=5,
                sampling_frequency_hz=2.0,
            )

    def test_source_window_end_must_exceed_start(
        self,
    ):
        with self.assertRaisesRegex(
            ECGModelSpecificationError,
            "source-window end",
        ):
            ECGLeadSourceWindow(
                lead_name="I",
                temporal_segment_index=0,
                start_seconds=2.5,
                end_seconds_exclusive=2.5,
                sample_count=5,
                sampling_frequency_hz=2.0,
            )

    def test_invalid_source_window_sample_count_is_rejected(
        self,
    ):
        with self.assertRaisesRegex(
            ECGModelSpecificationError,
            "sample count",
        ):
            ECGLeadSourceWindow(
                lead_name="I",
                temporal_segment_index=0,
                start_seconds=0.0,
                end_seconds_exclusive=2.5,
                sample_count=0,
                sampling_frequency_hz=2.0,
            )

    def test_invalid_source_window_sampling_frequency_is_rejected(
        self,
    ):
        with self.assertRaisesRegex(
            ECGModelSpecificationError,
            "sampling frequency",
        ):
            ECGLeadSourceWindow(
                lead_name="I",
                temporal_segment_index=0,
                start_seconds=0.0,
                end_seconds_exclusive=2.5,
                sample_count=5,
                sampling_frequency_hz=0.0,
            )

    # =====================================================
    # Valid Complete Specification
    # =====================================================

    def test_valid_multilabel_specification_is_created(
        self,
    ):
        specification = (
            self._valid_specification()
        )

        self.assertEqual(
            specification.model_name,
            "synthetic_ecg_model",
        )

        self.assertEqual(
            specification.model_version,
            "1.0.0",
        )

        self.assertEqual(
            specification.label_count,
            2,
        )

        self.assertEqual(
            specification.label_names,
            (
                "class_a",
                "class_b",
            ),
        )

        self.assertEqual(
            specification.input_temporal_layout,
            INPUT_TEMPORAL_LAYOUT_SYNCHRONOUS_12_LEAD,
        )

        self.assertTrue(
            specification.has_complete_thresholds
        )

    def test_target_duration_and_window_span_are_distinct(
        self,
    ):
        specification = (
            self._valid_specification(
                input_sampling_frequency_hz=2.0,
                input_sample_count=5,
            )
        )

        # First sample is at t=0 and final sample is at t=2.0.
        self.assertAlmostEqual(
            specification.target_duration_seconds,
            2.0,
        )

        # Five digital samples at 2 Hz occupy [0.0, 2.5).
        self.assertAlmostEqual(
            specification.input_window_span_seconds,
            2.5,
        )

    def test_window_start_is_included_in_both_window_end_properties(
        self,
    ):
        specification = (
            self._valid_specification(
                input_sampling_frequency_hz=2.0,
                input_sample_count=5,
                window_start_seconds=1.5,
            )
        )

        self.assertAlmostEqual(
            specification.target_duration_seconds,
            2.0,
        )

        self.assertAlmostEqual(
            specification.window_end_seconds,
            3.5,
        )

        self.assertAlmostEqual(
            specification.window_end_seconds_exclusive,
            4.0,
        )

    def test_synchronous_specification_uses_one_source_segment(
        self,
    ):
        specification = (
            self._valid_specification()
        )

        self.assertFalse(
            specification.uses_sequential_print_layout
        )

        self.assertEqual(
            specification.source_temporal_segment_count,
            1,
        )

        self.assertAlmostEqual(
            specification.minimum_source_recording_span_seconds,
            2.5,
        )

    # =====================================================
    # Label Collection Validation
    # =====================================================

    def test_empty_label_collection_is_rejected(
        self,
    ):
        with self.assertRaisesRegex(
            ECGModelSpecificationError,
            "at least one output label",
        ):
            self._valid_specification(
                labels=(),
            )

    def test_non_label_object_is_rejected(
        self,
    ):
        with self.assertRaisesRegex(
            ECGModelSpecificationError,
            "ECGLabelSpecification",
        ):
            self._valid_specification(
                labels=(
                    "class_a",
                ),
            )

    def test_duplicate_label_names_are_rejected(
        self,
    ):
        labels = (
            ECGLabelSpecification(
                name="class_a",
                decision_threshold=0.40,
            ),
            ECGLabelSpecification(
                name="class_a",
                decision_threshold=0.60,
            ),
        )

        with self.assertRaisesRegex(
            ECGModelSpecificationError,
            "duplicate",
        ):
            self._valid_specification(
                labels=labels,
            )

    # =====================================================
    # Output Semantics
    # =====================================================

    def test_unsupported_output_semantics_are_rejected(
        self,
    ):
        with self.assertRaisesRegex(
            ECGModelSpecificationError,
            "Unsupported ECG model output semantics",
        ):
            self._valid_specification(
                output_semantics="unsupported",
            )

    def test_multilabel_requires_threshold_for_every_label(
        self,
    ):
        labels = (
            ECGLabelSpecification(
                name="class_a",
                decision_threshold=0.40,
            ),
            ECGLabelSpecification(
                name="class_b",
                decision_threshold=None,
            ),
        )

        with self.assertRaisesRegex(
            ECGModelSpecificationError,
            "Missing thresholds: class_b",
        ):
            self._valid_specification(
                labels=labels,
                output_semantics=(
                    OUTPUT_MULTILABEL_PROBABILITY
                ),
            )

    def test_binary_semantics_do_not_force_per_label_threshold(
        self,
    ):
        labels = (
            ECGLabelSpecification(
                name="class_a",
                decision_threshold=None,
            ),
        )

        specification = (
            self._valid_specification(
                labels=labels,
                output_semantics=(
                    OUTPUT_BINARY_PROBABILITY
                ),
            )
        )

        self.assertFalse(
            specification.has_complete_thresholds
        )

    def test_multiclass_semantics_do_not_force_per_label_thresholds(
        self,
    ):
        labels = (
            ECGLabelSpecification(
                name="class_a",
            ),
            ECGLabelSpecification(
                name="class_b",
            ),
        )

        specification = (
            self._valid_specification(
                labels=labels,
                output_semantics=(
                    OUTPUT_MULTICLASS_PROBABILITY
                ),
            )
        )

        self.assertFalse(
            specification.has_complete_thresholds
        )

    # =====================================================
    # Label Lookup and Threshold Access
    # =====================================================

    def test_get_label_returns_requested_label(
        self,
    ):
        specification = (
            self._valid_specification()
        )

        label = specification.get_label(
            "class_b"
        )

        self.assertIsNotNone(
            label
        )

        self.assertEqual(
            label.name,
            "class_b",
        )

        self.assertEqual(
            label.decision_threshold,
            0.65,
        )

    def test_get_label_returns_none_for_unknown_label(
        self,
    ):
        specification = (
            self._valid_specification()
        )

        self.assertIsNone(
            specification.get_label(
                "unknown"
            )
        )

    def test_threshold_for_returns_configured_threshold(
        self,
    ):
        specification = (
            self._valid_specification()
        )

        self.assertEqual(
            specification.threshold_for(
                "class_a"
            ),
            0.40,
        )

    def test_threshold_for_unknown_label_is_rejected(
        self,
    ):
        specification = (
            self._valid_specification()
        )

        with self.assertRaisesRegex(
            ECGModelSpecificationError,
            "Unknown ECG model output label",
        ):
            specification.threshold_for(
                "unknown"
            )

    def test_decision_threshold_pairs_preserve_label_order(
        self,
    ):
        specification = (
            self._valid_specification()
        )

        self.assertEqual(
            specification.decision_thresholds,
            (
                (
                    "class_a",
                    0.40,
                ),
                (
                    "class_b",
                    0.65,
                ),
            ),
        )

    # =====================================================
    # Standard 3x4 Temporal Mapping
    # =====================================================

    def test_standard_3x4_sequential_columns_match_existing_layout(
        self,
    ):
        self.assertEqual(
            STANDARD_3X4_SEQUENTIAL_COLUMNS,
            (
                (
                    "I",
                    "II",
                    "III",
                ),
                (
                    "aVR",
                    "aVL",
                    "aVF",
                ),
                (
                    "V1",
                    "V2",
                    "V3",
                ),
                (
                    "V4",
                    "V5",
                    "V6",
                ),
            ),
        )

    def test_blank_input_temporal_layout_is_rejected(
        self,
    ):
        with self.assertRaisesRegex(
            ECGModelSpecificationError,
            "temporal layout cannot be empty",
        ):
            self._valid_specification(
                input_temporal_layout="",
            )

    def test_unsupported_input_temporal_layout_is_rejected(
        self,
    ):
        with self.assertRaisesRegex(
            ECGModelSpecificationError,
            "Unsupported ECG model input temporal layout",
        ):
            self._valid_specification(
                input_temporal_layout="unsupported",
            )

    def test_synchronous_layout_rejects_source_column_duration(
        self,
    ):
        with self.assertRaisesRegex(
            ECGModelSpecificationError,
            "must not define",
        ):
            self._valid_specification(
                input_temporal_layout=(
                    INPUT_TEMPORAL_LAYOUT_SYNCHRONOUS_12_LEAD
                ),
                source_column_duration_seconds=2.5,
            )

    def test_synchronous_layout_places_every_lead_in_segment_zero(
        self,
    ):
        specification = (
            self._valid_specification()
        )

        for lead_name in STANDARD_ECG_LEAD_NAMES:
            self.assertEqual(
                specification.temporal_segment_for_lead(
                    lead_name
                ),
                0,
            )

    def test_synchronous_layout_uses_same_source_window_for_all_leads(
        self,
    ):
        specification = (
            self._valid_specification()
        )

        windows = (
            specification.lead_source_windows
        )

        self.assertEqual(
            len(
                windows
            ),
            12,
        )

        for window in windows:
            self.assertEqual(
                window.temporal_segment_index,
                0,
            )

            self.assertAlmostEqual(
                window.start_seconds,
                0.0,
            )

            self.assertAlmostEqual(
                window.end_seconds_exclusive,
                2.5,
            )

            self.assertEqual(
                window.sample_count,
                5,
            )

            self.assertAlmostEqual(
                window.sampling_frequency_hz,
                2.0,
            )

    def test_sequential_layout_requires_source_column_duration(
        self,
    ):
        with self.assertRaisesRegex(
            ECGModelSpecificationError,
            "require an explicit source-column duration",
        ):
            self._valid_specification(
                input_temporal_layout=(
                    INPUT_TEMPORAL_LAYOUT_STANDARD_3X4_SEQUENTIAL
                ),
                source_column_duration_seconds=None,
            )

    def test_sequential_source_column_duration_must_be_numeric(
        self,
    ):
        with self.assertRaisesRegex(
            ECGModelSpecificationError,
            "source-column duration must be numeric",
        ):
            self._valid_specification(
                input_temporal_layout=(
                    INPUT_TEMPORAL_LAYOUT_STANDARD_3X4_SEQUENTIAL
                ),
                source_column_duration_seconds="invalid",
            )

    def test_sequential_source_column_duration_must_be_positive(
        self,
    ):
        with self.assertRaisesRegex(
            ECGModelSpecificationError,
            "positive finite number",
        ):
            self._valid_specification(
                input_temporal_layout=(
                    INPUT_TEMPORAL_LAYOUT_STANDARD_3X4_SEQUENTIAL
                ),
                source_column_duration_seconds=0.0,
            )

    def test_sequential_model_window_must_fit_inside_one_column(
        self,
    ):
        with self.assertRaisesRegex(
            ECGModelSpecificationError,
            "does not fit",
        ):
            self._valid_specification(
                input_temporal_layout=(
                    INPUT_TEMPORAL_LAYOUT_STANDARD_3X4_SEQUENTIAL
                ),
                source_column_duration_seconds=2.0,
                input_sampling_frequency_hz=2.0,
                input_sample_count=5,
            )

    def test_sequential_layout_reports_four_source_segments(
        self,
    ):
        specification = (
            self._valid_sequential_specification()
        )

        self.assertTrue(
            specification.uses_sequential_print_layout
        )

        self.assertEqual(
            specification.source_temporal_segment_count,
            4,
        )

    def test_sequential_temporal_segment_mapping_matches_print_columns(
        self,
    ):
        specification = (
            self._valid_sequential_specification()
        )

        expected_segments = {
            "I": 0,
            "II": 0,
            "III": 0,
            "aVR": 1,
            "aVL": 1,
            "aVF": 1,
            "V1": 2,
            "V2": 2,
            "V3": 2,
            "V4": 3,
            "V5": 3,
            "V6": 3,
        }

        for (
            lead_name,
            expected_segment,
        ) in expected_segments.items():
            self.assertEqual(
                specification.temporal_segment_for_lead(
                    lead_name
                ),
                expected_segment,
            )

    def test_unknown_canonical_lead_is_rejected(
        self,
    ):
        specification = (
            self._valid_sequential_specification()
        )

        with self.assertRaisesRegex(
            ECGModelSpecificationError,
            "Unknown canonical ECG lead",
        ):
            specification.temporal_segment_for_lead(
                "unknown"
            )

    def test_sequential_source_windows_match_four_successive_columns(
        self,
    ):
        specification = (
            self._valid_sequential_specification()
        )

        expected_windows = {
            "I": (
                0,
                0.0,
                2.5,
            ),
            "II": (
                0,
                0.0,
                2.5,
            ),
            "III": (
                0,
                0.0,
                2.5,
            ),
            "aVR": (
                1,
                2.5,
                5.0,
            ),
            "aVL": (
                1,
                2.5,
                5.0,
            ),
            "aVF": (
                1,
                2.5,
                5.0,
            ),
            "V1": (
                2,
                5.0,
                7.5,
            ),
            "V2": (
                2,
                5.0,
                7.5,
            ),
            "V3": (
                2,
                5.0,
                7.5,
            ),
            "V4": (
                3,
                7.5,
                10.0,
            ),
            "V5": (
                3,
                7.5,
                10.0,
            ),
            "V6": (
                3,
                7.5,
                10.0,
            ),
        }

        for (
            lead_name,
            (
                expected_segment,
                expected_start,
                expected_end,
            ),
        ) in expected_windows.items():
            window = (
                specification.source_window_for_lead(
                    lead_name
                )
            )

            self.assertEqual(
                window.lead_name,
                lead_name,
            )

            self.assertEqual(
                window.temporal_segment_index,
                expected_segment,
            )

            self.assertAlmostEqual(
                window.start_seconds,
                expected_start,
            )

            self.assertAlmostEqual(
                window.end_seconds_exclusive,
                expected_end,
            )

    def test_sequential_lead_source_windows_remain_in_canonical_order(
        self,
    ):
        specification = (
            self._valid_sequential_specification()
        )

        self.assertEqual(
            tuple(
                window.lead_name
                for window in specification.lead_source_windows
            ),
            tuple(
                STANDARD_ECG_LEAD_NAMES
            ),
        )

    def test_sequential_minimum_source_recording_span_is_four_columns(
        self,
    ):
        specification = (
            self._valid_sequential_specification()
        )

        self.assertAlmostEqual(
            specification.minimum_source_recording_span_seconds,
            10.0,
        )

    def test_sequential_local_window_offset_is_applied_inside_each_column(
        self,
    ):
        specification = (
            self._valid_sequential_specification(
                source_column_duration_seconds=3.0,
                input_sampling_frequency_hz=2.0,
                input_sample_count=4,
                window_start_seconds=0.5,
            )
        )

        # Four samples at 2 Hz occupy an exclusive span of 2.0 s.
        # With a local offset of 0.5 s inside each 3-second column:
        #
        # I   -> [0.5, 2.5)
        # aVR -> [3.5, 5.5)
        # V1  -> [6.5, 8.5)
        # V4  -> [9.5, 11.5)

        expected = {
            "I": (
                0.5,
                2.5,
            ),
            "aVR": (
                3.5,
                5.5,
            ),
            "V1": (
                6.5,
                8.5,
            ),
            "V4": (
                9.5,
                11.5,
            ),
        }

        for (
            lead_name,
            (
                expected_start,
                expected_end,
            ),
        ) in expected.items():
            window = (
                specification.source_window_for_lead(
                    lead_name
                )
            )

            self.assertAlmostEqual(
                window.start_seconds,
                expected_start,
            )

            self.assertAlmostEqual(
                window.end_seconds_exclusive,
                expected_end,
            )

    # =====================================================
    # Preprocessing Contract Conversion
    # =====================================================

    def test_builds_matching_preprocessing_config(
        self,
    ):
        specification = (
            self._valid_specification(
                input_sampling_frequency_hz=4.0,
                input_sample_count=9,
                preprocessing_version=(
                    "ecg-preprocess-v7"
                ),
                normalization_method=(
                    NORMALIZATION_ZSCORE_PER_LEAD
                ),
                missing_data_method=(
                    MISSING_DATA_LINEAR_INTERPOLATION
                ),
                max_missing_fraction_per_lead=0.20,
                max_interpolation_gap_seconds=0.50,
                window_start_seconds=1.0,
            )
        )

        config = (
            specification.to_preprocessing_config()
        )

        self.assertIsInstance(
            config,
            ECGPreprocessingConfig,
        )

        self.assertEqual(
            config.target_sampling_frequency_hz,
            4.0,
        )

        self.assertEqual(
            config.target_sample_count,
            9,
        )

        self.assertEqual(
            config.preprocessing_version,
            "ecg-preprocess-v7",
        )

        self.assertEqual(
            config.normalization_method,
            NORMALIZATION_ZSCORE_PER_LEAD,
        )

        self.assertEqual(
            config.missing_data_method,
            MISSING_DATA_LINEAR_INTERPOLATION,
        )

        self.assertEqual(
            config.max_missing_fraction_per_lead,
            0.20,
        )

        self.assertEqual(
            config.max_interpolation_gap_seconds,
            0.50,
        )

        self.assertEqual(
            config.window_start_seconds,
            1.0,
        )

    def test_invalid_normalization_is_rejected_through_preprocessing_contract(
        self,
    ):
        with self.assertRaisesRegex(
            ECGModelSpecificationError,
            "preprocessing specification is invalid",
        ):
            self._valid_specification(
                normalization_method="invalid",
            )

    def test_invalid_missing_data_configuration_is_rejected(
        self,
    ):
        with self.assertRaisesRegex(
            ECGModelSpecificationError,
            "preprocessing specification is invalid",
        ):
            self._valid_specification(
                missing_data_method=(
                    MISSING_DATA_REJECT
                ),
                max_missing_fraction_per_lead=0.25,
            )

    # =====================================================
    # Model Metadata Conversion
    # =====================================================

    def test_builds_matching_model_metadata(
        self,
    ):
        specification = (
            self._valid_specification(
                model_name="synthetic_ecg_model",
                model_version="3.2.1",
                task="synthetic_task",
                framework="synthetic_framework",
                preprocessing_version=(
                    "ecg-preprocess-v3"
                ),
                normalization_method=(
                    NORMALIZATION_ZSCORE_PER_LEAD
                ),
            )
        )

        metadata = (
            specification.to_model_metadata()
        )

        self.assertIsInstance(
            metadata,
            ECGModelMetadata,
        )

        self.assertEqual(
            metadata.model_name,
            "synthetic_ecg_model",
        )

        self.assertEqual(
            metadata.model_version,
            "3.2.1",
        )

        self.assertEqual(
            metadata.task,
            "synthetic_task",
        )

        self.assertEqual(
            metadata.framework,
            "synthetic_framework",
        )

        self.assertEqual(
            metadata.labels,
            (
                "class_a",
                "class_b",
            ),
        )

        self.assertEqual(
            metadata.input_sampling_frequency_hz,
            2.0,
        )

        self.assertEqual(
            metadata.input_sample_count,
            5,
        )

        self.assertEqual(
            metadata.preprocessing_version,
            "ecg-preprocess-v3",
        )

        self.assertEqual(
            metadata.normalization_method,
            NORMALIZATION_ZSCORE_PER_LEAD,
        )

        self.assertEqual(
            metadata.output_semantics,
            OUTPUT_MULTILABEL_PROBABILITY,
        )

    def test_invalid_model_identity_is_rejected_through_metadata_contract(
        self,
    ):
        with self.assertRaisesRegex(
            ECGModelSpecificationError,
            "metadata specification is invalid",
        ):
            self._valid_specification(
                model_name="",
            )

    # =====================================================
    # Artifact SHA-256
    # =====================================================

    def test_empty_artifact_fingerprint_is_allowed_before_model_exists(
        self,
    ):
        specification = (
            self._valid_specification(
                artifact_sha256="",
            )
        )

        self.assertEqual(
            specification.artifact_sha256,
            "",
        )

    def test_valid_artifact_sha256_is_accepted(
        self,
    ):
        fingerprint = (
            "a" * 64
        )

        specification = (
            self._valid_specification(
                artifact_sha256=fingerprint,
            )
        )

        self.assertEqual(
            specification.artifact_sha256,
            fingerprint,
        )

    def test_wrong_length_artifact_sha256_is_rejected(
        self,
    ):
        with self.assertRaisesRegex(
            ECGModelSpecificationError,
            "exactly 64",
        ):
            self._valid_specification(
                artifact_sha256=(
                    "a" * 63
                ),
            )

    def test_non_hexadecimal_artifact_sha256_is_rejected(
        self,
    ):
        fingerprint = (
            "g" * 64
        )

        with self.assertRaisesRegex(
            ECGModelSpecificationError,
            "only hexadecimal",
        ):
            self._valid_specification(
                artifact_sha256=fingerprint,
            )