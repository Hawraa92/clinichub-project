"""

Tests for the model-agnostic ECG AI interface.

These tests verify:

    - Prepared twelve-lead model input validation.

    - ECG model metadata validation.

    - Structured prediction-score validation.

    - Structured model-prediction validation.

    - Adapter readiness checks.

    - Compatibility checks between prepared input and model metadata.

    - Explicit temporal-layout validation and compatibility checks.

    - Validation of model output before application use.

No real trained ECG model is loaded here.

No clinical diagnosis or XAI explanation is produced.

"""

import math

from django.test import SimpleTestCase

from ecg.services.ai.model_interface import (

    ECGModelAdapter,

    ECGModelError,

    ECGModelInputError,

    ECGModelMetadata,

    ECGModelNotReadyError,

    ECGModelOutputError,

    ECGModelPrediction,

    ECGPredictionScore,

    ECGPreparedModelInput,

    INPUT_TEMPORAL_LAYOUT_STANDARD_3X4_SEQUENTIAL,

    INPUT_TEMPORAL_LAYOUT_SYNCHRONOUS_12_LEAD,

)

from ecg.services.lead_identification import (

    STANDARD_ECG_LEAD_NAMES,

)

class DummyECGModelAdapter(ECGModelAdapter):

    """

    Small deterministic model adapter used only for interface tests.

    It does not perform real AI inference.

    """

    def __init__(

        self,

        *,

        ready=False,

        metadata=None,

        prediction=None,

    ):

        self._ready = ready

        self._metadata = (

            metadata

            if metadata is not None

            else ECGModelMetadata(

                model_name="test_ecg_model",

                model_version="1.0.0",

                task="multilabel_ecg_classification",

                framework="test",

                labels=(

                    "normal",

                    "atrial_fibrillation",

                ),

                input_sampling_frequency_hz=500.0,

                input_sample_count=4,

                preprocessing_version="ecg-preprocess-v1",

                normalization_method="zscore",

                input_temporal_layout=(

                    INPUT_TEMPORAL_LAYOUT_SYNCHRONOUS_12_LEAD

                ),

                output_semantics="multilabel_probability",

            )

        )

        self._prediction = (

            prediction

            if prediction is not None

            else ECGModelPrediction(

                model_name=(

                    self._metadata.model_name

                ),

                model_version=(

                    self._metadata.model_version

                ),

                scores=(

                    ECGPredictionScore(

                        label="normal",

                        score=0.20,

                        selected=False,

                        decision_threshold=0.50,

                    ),

                    ECGPredictionScore(

                        label="atrial_fibrillation",

                        score=0.80,

                        selected=True,

                        decision_threshold=0.50,

                    ),

                ),

            )

        )

    @property

    def metadata(self):

        return self._metadata

    @property

    def is_ready(self):

        return self._ready

    def load(self):

        self._ready = True

    def _predict(

        self,

        model_input,

    ):

        return self._prediction

class ECGModelInterfaceTests(SimpleTestCase):

    """

    Unit tests for the ECG model-agnostic inference contract.

    """

    def _valid_samples(

        self,

        *,

        sample_count=4,

    ):

        """

        Return twelve deterministic equal-length ECG lead arrays.

        """

        return tuple(

            tuple(

                float(

                    lead_index + sample_index

                )

                for sample_index in range(

                    sample_count

                )

            )

            for lead_index in range(

                12

            )

        )

    def _valid_model_input(

        self,

        *,

        lead_names=None,

        samples=None,

        sampling_frequency_hz=500.0,

        preprocessing_version="ecg-preprocess-v1",

        normalization_method="zscore",

        input_temporal_layout=(

            INPUT_TEMPORAL_LAYOUT_SYNCHRONOUS_12_LEAD

        ),

    ):

        if lead_names is None:

            lead_names = tuple(

                STANDARD_ECG_LEAD_NAMES

            )

        if samples is None:

            samples = self._valid_samples()

        return ECGPreparedModelInput(

            lead_names=lead_names,

            samples=samples,

            sampling_frequency_hz=(

                sampling_frequency_hz

            ),

            preprocessing_version=(

                preprocessing_version

            ),

            normalization_method=(

                normalization_method

            ),

            input_temporal_layout=(

                input_temporal_layout

            ),

        )

    def _valid_metadata(

        self,

        **overrides,

    ):

        values = {

            "model_name": "test_ecg_model",

            "model_version": "1.0.0",

            "task": "multilabel_ecg_classification",

            "framework": "test",

            "labels": (

                "normal",

                "atrial_fibrillation",

            ),

            "input_sampling_frequency_hz": 500.0,

            "input_sample_count": 4,

            "preprocessing_version": (

                "ecg-preprocess-v1"

            ),

            "normalization_method": (

                "zscore"

            ),

            "input_temporal_layout": (

                INPUT_TEMPORAL_LAYOUT_SYNCHRONOUS_12_LEAD

            ),

            "output_semantics": (

                "multilabel_probability"

            ),

            "artifact_sha256": "",

        }

        values.update(

            overrides

        )

        return ECGModelMetadata(

            **values

        )

    # =====================================================

    # Prepared Model Input

    # =====================================================

    def test_valid_prepared_input_exposes_expected_shape(

        self,

    ):

        model_input = (

            self._valid_model_input()

        )

        self.assertEqual(

            model_input.lead_count,

            12,

        )

        self.assertEqual(

            model_input.sample_count,

            4,

        )

        self.assertEqual(

            model_input.shape,

            (

                12,

                4,

            ),

        )

    def test_valid_prepared_input_exposes_synchronous_temporal_layout(

        self,

    ):

        model_input = self._valid_model_input()

        self.assertEqual(

            model_input.input_temporal_layout,

            INPUT_TEMPORAL_LAYOUT_SYNCHRONOUS_12_LEAD,

        )

        self.assertFalse(

            model_input.uses_sequential_print_layout

        )

    def test_sequential_prepared_input_exposes_expected_temporal_layout(

        self,

    ):

        model_input = self._valid_model_input(

            input_temporal_layout=(

                INPUT_TEMPORAL_LAYOUT_STANDARD_3X4_SEQUENTIAL

            ),

        )

        self.assertEqual(

            model_input.input_temporal_layout,

            INPUT_TEMPORAL_LAYOUT_STANDARD_3X4_SEQUENTIAL,

        )

        self.assertTrue(

            model_input.uses_sequential_print_layout

        )

    def test_blank_prepared_input_temporal_layout_is_rejected(

        self,

    ):

        with self.assertRaises(

            ECGModelInputError

        ):

            self._valid_model_input(

                input_temporal_layout="",

            )

    def test_unsupported_prepared_input_temporal_layout_is_rejected(

        self,

    ):

        with self.assertRaises(

            ECGModelInputError

        ):

            self._valid_model_input(

                input_temporal_layout="unsupported-layout",

            )

    def test_noncanonical_lead_order_is_rejected(

        self,

    ):

        reversed_names = tuple(

            reversed(

                STANDARD_ECG_LEAD_NAMES

            )

        )

        with self.assertRaisesRegex(

            ECGModelInputError,

            "canonical twelve ECG leads",

        ):

            self._valid_model_input(

                lead_names=reversed_names,

            )

    def test_missing_lead_sample_array_is_rejected(

        self,

    ):

        samples = (

            self._valid_samples()[:-1]

        )

        with self.assertRaisesRegex(

            ECGModelInputError,

            "exactly twelve",

        ):

            self._valid_model_input(

                samples=samples,

            )

    def test_empty_lead_samples_are_rejected(

        self,

    ):

        samples = list(

            self._valid_samples()

        )

        samples[0] = ()

        with self.assertRaisesRegex(

            ECGModelInputError,

            "contains no samples",

        ):

            self._valid_model_input(

                samples=tuple(

                    samples

                ),

            )

    def test_different_lead_sample_lengths_are_rejected(

        self,

    ):

        samples = list(

            self._valid_samples()

        )

        samples[1] = (

            1.0,

            2.0,

        )

        with self.assertRaisesRegex(

            ECGModelInputError,

            "same number of samples",

        ):

            self._valid_model_input(

                samples=tuple(

                    samples

                ),

            )

    def test_non_numeric_sample_is_rejected(

        self,

    ):

        samples = list(

            self._valid_samples()

        )

        samples[0] = (

            1.0,

            2.0,

            "invalid",

            4.0,

        )

        with self.assertRaisesRegex(

            ECGModelInputError,

            "non-numeric sample",

        ):

            self._valid_model_input(

                samples=tuple(

                    samples

                ),

            )

    def test_non_finite_sample_is_rejected(

        self,

    ):

        samples = list(

            self._valid_samples()

        )

        samples[0] = (

            1.0,

            2.0,

            math.inf,

            4.0,

        )

        with self.assertRaisesRegex(

            ECGModelInputError,

            "non-finite sample",

        ):

            self._valid_model_input(

                samples=tuple(

                    samples

                ),

            )

    def test_zero_sampling_frequency_is_rejected(

        self,

    ):

        with self.assertRaisesRegex(

            ECGModelInputError,

            "positive finite number",

        ):

            self._valid_model_input(

                sampling_frequency_hz=0,

            )

    def test_non_finite_sampling_frequency_is_rejected(

        self,

    ):

        with self.assertRaisesRegex(

            ECGModelInputError,

            "positive finite number",

        ):

            self._valid_model_input(

                sampling_frequency_hz=math.inf,

            )

    def test_blank_preprocessing_version_is_rejected(

        self,

    ):

        with self.assertRaisesRegex(

            ECGModelInputError,

            "preprocessing version",

        ):

            self._valid_model_input(

                preprocessing_version="",

            )

    def test_blank_normalization_method_is_rejected(

        self,

    ):

        with self.assertRaisesRegex(

            ECGModelInputError,

            "normalization method",

        ):

            self._valid_model_input(

                normalization_method="",

            )

    # =====================================================

    # Model Metadata

    # =====================================================

    def test_valid_model_metadata_is_created(

        self,

    ):

        metadata = (

            self._valid_metadata()

        )

        self.assertEqual(

            metadata.model_name,

            "test_ecg_model",

        )

        self.assertEqual(

            metadata.input_sample_count,

            4,

        )

        self.assertEqual(

            metadata.labels,

            (

                "normal",

                "atrial_fibrillation",

            ),

        )

        self.assertEqual(

            metadata.normalization_method,

            "zscore",

        )

    def test_valid_model_metadata_exposes_temporal_layout(

        self,

    ):

        metadata = self._valid_metadata()

        self.assertEqual(

            metadata.input_temporal_layout,

            INPUT_TEMPORAL_LAYOUT_SYNCHRONOUS_12_LEAD,

        )

    def test_sequential_model_metadata_is_created(

        self,

    ):

        metadata = self._valid_metadata(

            input_temporal_layout=(

                INPUT_TEMPORAL_LAYOUT_STANDARD_3X4_SEQUENTIAL

            ),

        )

        self.assertEqual(

            metadata.input_temporal_layout,

            INPUT_TEMPORAL_LAYOUT_STANDARD_3X4_SEQUENTIAL,

        )

    def test_blank_metadata_temporal_layout_is_rejected(

        self,

    ):

        with self.assertRaises(

            ECGModelError

        ):

            self._valid_metadata(

                input_temporal_layout="",

            )

    def test_unsupported_metadata_temporal_layout_is_rejected(

        self,

    ):

        with self.assertRaises(

            ECGModelError

        ):

            self._valid_metadata(

                input_temporal_layout="unsupported-layout",

            )

    def test_empty_model_name_is_rejected(

        self,

    ):

        with self.assertRaisesRegex(

            ECGModelError,

            "model name",

        ):

            self._valid_metadata(

                model_name="",

            )

    def test_duplicate_model_labels_are_rejected(

        self,

    ):

        with self.assertRaisesRegex(

            ECGModelError,

            "labels must be unique",

        ):

            self._valid_metadata(

                labels=(

                    "normal",

                    "normal",

                ),

            )

    def test_zero_metadata_sampling_frequency_is_rejected(

        self,

    ):

        with self.assertRaisesRegex(

            ECGModelError,

            "sampling frequency",

        ):

            self._valid_metadata(

                input_sampling_frequency_hz=0,

            )

    def test_zero_model_sample_count_is_rejected(

        self,

    ):

        with self.assertRaisesRegex(

            ECGModelError,

            "positive integer",

        ):

            self._valid_metadata(

                input_sample_count=0,

            )

    def test_boolean_model_sample_count_is_rejected(

        self,

    ):

        with self.assertRaisesRegex(

            ECGModelError,

            "positive integer",

        ):

            self._valid_metadata(

                input_sample_count=True,

            )

    def test_blank_metadata_normalization_method_is_rejected(

        self,

    ):

        with self.assertRaisesRegex(

            ECGModelError,

            "normalization method",

        ):

            self._valid_metadata(

                normalization_method="",

            )

    # =====================================================

    # Prediction Scores

    # =====================================================

    def test_valid_prediction_score_is_created(

        self,

    ):

        score = ECGPredictionScore(

            label="normal",

            score=0.80,

            selected=True,

            decision_threshold=0.50,

        )

        self.assertEqual(

            score.label,

            "normal",

        )

        self.assertEqual(

            score.score,

            0.80,

        )

        self.assertTrue(

            score.selected

        )

    def test_prediction_score_below_zero_is_rejected(

        self,

    ):

        with self.assertRaisesRegex(

            ECGModelOutputError,

            "between 0 and 1",

        ):

            ECGPredictionScore(

                label="normal",

                score=-0.01,

                selected=False,

            )

    def test_prediction_score_above_one_is_rejected(

        self,

    ):

        with self.assertRaisesRegex(

            ECGModelOutputError,

            "between 0 and 1",

        ):

            ECGPredictionScore(

                label="normal",

                score=1.01,

                selected=True,

            )

    def test_prediction_selected_state_must_be_boolean(

        self,

    ):

        with self.assertRaisesRegex(

            ECGModelOutputError,

            "must be boolean",

        ):

            ECGPredictionScore(

                label="normal",

                score=0.50,

                selected=1,

            )

    def test_invalid_prediction_threshold_is_rejected(

        self,

    ):

        with self.assertRaisesRegex(

            ECGModelOutputError,

            "between 0 and 1",

        ):

            ECGPredictionScore(

                label="normal",

                score=0.50,

                selected=True,

                decision_threshold=1.50,

            )

    # =====================================================

    # Structured Prediction

    # =====================================================

    def test_prediction_supports_multiple_selected_labels(

        self,

    ):

        prediction = ECGModelPrediction(

            model_name="test_ecg_model",

            model_version="1.0.0",

            scores=(

                ECGPredictionScore(

                    label="atrial_fibrillation",

                    score=0.90,

                    selected=True,

                    decision_threshold=0.50,

                ),

                ECGPredictionScore(

                    label="tachycardia",

                    score=0.80,

                    selected=True,

                    decision_threshold=0.50,

                ),

                ECGPredictionScore(

                    label="normal",

                    score=0.10,

                    selected=False,

                    decision_threshold=0.50,

                ),

            ),

        )

        self.assertEqual(

            prediction.selected_labels,

            (

                "atrial_fibrillation",

                "tachycardia",

            ),

        )

        self.assertEqual(

            prediction.selected_count,

            2,

        )

        self.assertEqual(

            prediction.get_score(

                "normal"

            ).score,

            0.10,

        )

    def test_duplicate_prediction_labels_are_rejected(

        self,

    ):

        with self.assertRaisesRegex(

            ECGModelOutputError,

            "duplicate labels",

        ):

            ECGModelPrediction(

                model_name="test_ecg_model",

                model_version="1.0.0",

                scores=(

                    ECGPredictionScore(

                        label="normal",

                        score=0.70,

                        selected=True,

                    ),

                    ECGPredictionScore(

                        label="normal",

                        score=0.30,

                        selected=False,

                    ),

                ),

            )

    def test_prediction_rejects_non_score_object(

        self,

    ):

        with self.assertRaises(

            ECGModelOutputError

        ):

            ECGModelPrediction(

                model_name="test_ecg_model",

                model_version="1.0.0",

                scores=(

                    object(),

                ),

            )

    def test_empty_prediction_scores_are_rejected(

        self,

    ):

        with self.assertRaisesRegex(

            ECGModelOutputError,

            "at least one class score",

        ):

            ECGModelPrediction(

                model_name="test_ecg_model",

                model_version="1.0.0",

                scores=(),

            )

    # =====================================================

    # Adapter Readiness and Input Validation

    # =====================================================

    def test_adapter_rejects_inference_when_not_ready(

        self,

    ):

        adapter = DummyECGModelAdapter(

            ready=False,

        )

        model_input = (

            self._valid_model_input()

        )

        with self.assertRaisesRegex(

            ECGModelNotReadyError,

            "not ready",

        ):

            adapter.predict(

                model_input

            )

    def test_adapter_load_marks_model_ready(

        self,

    ):

        adapter = DummyECGModelAdapter(

            ready=False,

        )

        self.assertFalse(

            adapter.is_ready

        )

        adapter.load()

        self.assertTrue(

            adapter.is_ready

        )

    def test_adapter_rejects_wrong_input_type(

        self,

    ):

        adapter = DummyECGModelAdapter(

            ready=True,

        )

        with self.assertRaisesRegex(

            ECGModelInputError,

            "ECGPreparedModelInput",

        ):

            adapter.predict(

                object()

            )

    def test_adapter_rejects_wrong_sample_count(

        self,

    ):

        metadata = self._valid_metadata(

            input_sample_count=8,

        )

        adapter = DummyECGModelAdapter(

            ready=True,

            metadata=metadata,

        )

        model_input = (

            self._valid_model_input()

        )

        with self.assertRaisesRegex(

            ECGModelInputError,

            "sample count",

        ):

            adapter.predict(

                model_input

            )

    def test_adapter_rejects_wrong_sampling_frequency(

        self,

    ):

        adapter = DummyECGModelAdapter(

            ready=True,

        )

        model_input = (

            self._valid_model_input(

                sampling_frequency_hz=250.0,

            )

        )

        with self.assertRaisesRegex(

            ECGModelInputError,

            "sampling frequency",

        ):

            adapter.predict(

                model_input

            )

    def test_adapter_rejects_wrong_preprocessing_version(

        self,

    ):

        adapter = DummyECGModelAdapter(

            ready=True,

        )

        model_input = (

            self._valid_model_input(

                preprocessing_version=(

                    "different-version"

                ),

            )

        )

        with self.assertRaisesRegex(

            ECGModelInputError,

            "preprocessing version",

        ):

            adapter.predict(

                model_input

            )

    def test_adapter_rejects_wrong_normalization_method(

        self,

    ):

        adapter = DummyECGModelAdapter(

            ready=True,

        )

        model_input = (

            self._valid_model_input(

                normalization_method="none",

            )

        )

        with self.assertRaisesRegex(

            ECGModelInputError,

            "normalization method",

        ):

            adapter.predict(

                model_input

            )

    def test_adapter_rejects_wrong_temporal_layout(

        self,

    ):

        metadata = self._valid_metadata(

            input_temporal_layout=(

                INPUT_TEMPORAL_LAYOUT_STANDARD_3X4_SEQUENTIAL

            ),

        )

        adapter = DummyECGModelAdapter(

            ready=True,

            metadata=metadata,

        )

        model_input = self._valid_model_input(

            input_temporal_layout=(

                INPUT_TEMPORAL_LAYOUT_SYNCHRONOUS_12_LEAD

            ),

        )

        with self.assertRaisesRegex(

            ECGModelInputError,

            "temporal layout",

        ):

            adapter.predict(

                model_input

            )

    def test_adapter_accepts_matching_sequential_temporal_layout(

        self,

    ):

        metadata = self._valid_metadata(

            input_temporal_layout=(

                INPUT_TEMPORAL_LAYOUT_STANDARD_3X4_SEQUENTIAL

            ),

        )

        adapter = DummyECGModelAdapter(

            ready=True,

            metadata=metadata,

        )

        model_input = self._valid_model_input(

            input_temporal_layout=(

                INPUT_TEMPORAL_LAYOUT_STANDARD_3X4_SEQUENTIAL

            ),

        )

        prediction = adapter.predict(

            model_input

        )

        self.assertEqual(

            prediction.model_name,

            metadata.model_name,

        )

    # =====================================================

    # Adapter Prediction Validation

    # =====================================================

    def test_ready_adapter_returns_valid_prediction(

        self,

    ):

        adapter = DummyECGModelAdapter(

            ready=True,

        )

        model_input = (

            self._valid_model_input()

        )

        prediction = adapter.predict(

            model_input

        )

        self.assertEqual(

            prediction.model_name,

            "test_ecg_model",

        )

        self.assertEqual(

            prediction.model_version,

            "1.0.0",

        )

        self.assertEqual(

            prediction.selected_labels,

            (

                "atrial_fibrillation",

            ),

        )

    def test_prediction_model_name_mismatch_is_rejected(

        self,

    ):

        prediction = ECGModelPrediction(

            model_name="wrong_model",

            model_version="1.0.0",

            scores=(

                ECGPredictionScore(

                    label="normal",

                    score=0.20,

                    selected=False,

                ),

                ECGPredictionScore(

                    label="atrial_fibrillation",

                    score=0.80,

                    selected=True,

                ),

            ),

        )

        adapter = DummyECGModelAdapter(

            ready=True,

            prediction=prediction,

        )

        with self.assertRaisesRegex(

            ECGModelOutputError,

            "model name",

        ):

            adapter.predict(

                self._valid_model_input()

            )

    def test_prediction_model_version_mismatch_is_rejected(

        self,

    ):

        prediction = ECGModelPrediction(

            model_name="test_ecg_model",

            model_version="2.0.0",

            scores=(

                ECGPredictionScore(

                    label="normal",

                    score=0.20,

                    selected=False,

                ),

                ECGPredictionScore(

                    label="atrial_fibrillation",

                    score=0.80,

                    selected=True,

                ),

            ),

        )

        adapter = DummyECGModelAdapter(

            ready=True,

            prediction=prediction,

        )

        with self.assertRaisesRegex(

            ECGModelOutputError,

            "model version",

        ):

            adapter.predict(

                self._valid_model_input()

            )

    def test_prediction_label_set_mismatch_is_rejected(

        self,

    ):

        prediction = ECGModelPrediction(

            model_name="test_ecg_model",

            model_version="1.0.0",

            scores=(

                ECGPredictionScore(

                    label="normal",

                    score=0.20,

                    selected=False,

                ),

                ECGPredictionScore(

                    label="unexpected_label",

                    score=0.80,

                    selected=True,

                ),

            ),

        )

        adapter = DummyECGModelAdapter(

            ready=True,

            prediction=prediction,

        )

        with self.assertRaisesRegex(

            ECGModelOutputError,

            "labels do not match",

        ):

            adapter.predict(

                self._valid_model_input()

            )
