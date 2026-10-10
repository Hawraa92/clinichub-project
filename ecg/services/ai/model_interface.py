"""
Model-agnostic ECG AI inference contract.

This module defines the stable boundary between:

    ECG preprocessing
        ->
    prepared model input
        ->
    trained ECG model adapter
        ->
    structured model prediction

The module intentionally contains no trained model and performs no
clinical diagnosis.

Responsibilities:
    - Define the exact tensor-like ECG input expected by model adapters.
    - Preserve the canonical twelve-lead ECG order.
    - Require fixed-length, finite, fully prepared samples.
    - Preserve the temporal relationship represented by the twelve leads.
    - Describe model identity and preprocessing requirements.
    - Require training/inference temporal-layout compatibility.
    - Provide a model-agnostic adapter interface.
    - Represent single-label or multi-label model outputs consistently.
    - Keep model output separate from physician interpretation.

This module does NOT:
    - Load a specific trained ECG model.
    - Resample ECG signals.
    - Normalize ECG signals.
    - Interpolate missing samples.
    - Reconstruct sequential print-layout source windows.
    - Select clinical decision thresholds.
    - Generate XAI explanations.
    - Produce a final clinical diagnosis.

Those responsibilities belong to dedicated layers.
"""

from __future__ import annotations

import math
from abc import ABC, abstractmethod
from dataclasses import dataclass

from ecg.services.lead_identification import (
    STANDARD_ECG_LEAD_NAMES,
)


# =========================================================
# Supported Temporal Input Layouts
# =========================================================


INPUT_TEMPORAL_LAYOUT_SYNCHRONOUS_12_LEAD = (
    "synchronous_12_lead"
)

INPUT_TEMPORAL_LAYOUT_STANDARD_3X4_SEQUENTIAL = (
    "standard_3x4_sequential"
)


SUPPORTED_INPUT_TEMPORAL_LAYOUTS = (
    INPUT_TEMPORAL_LAYOUT_SYNCHRONOUS_12_LEAD,
    INPUT_TEMPORAL_LAYOUT_STANDARD_3X4_SEQUENTIAL,
)


# =========================================================
# Exceptions
# =========================================================


class ECGModelError(RuntimeError):
    """
    Base exception for ECG AI model-interface failures.
    """


class ECGModelNotReadyError(ECGModelError):
    """
    Raised when inference is requested before the model adapter
    is ready for prediction.
    """


class ECGModelInputError(ECGModelError):
    """
    Raised when prepared ECG data does not satisfy the model's
    declared input requirements.
    """


class ECGModelOutputError(ECGModelError):
    """
    Raised when a model adapter produces an invalid structured
    prediction.
    """


# =========================================================
# Shared Validation Helpers
# =========================================================


def _validate_input_temporal_layout(
    value,
    *,
    error_class,
    context,
):
    """
    Validate one explicit twelve-lead temporal-layout declaration.

    The model interface supports two distinct meanings of a prepared
    twelve-lead tensor:

        synchronous_12_lead
            All twelve leads represent the same source time interval.

        standard_3x4_sequential
            The leads reproduce the temporal structure of the
            supported sequential standard 3x4 ECG print layout.

    The actual source-window construction belongs to model
    specification / dataset-preparation layers. This function only
    validates the declared semantic contract.
    """

    if (
        not isinstance(
            value,
            str,
        )
        or not value.strip()
    ):
        raise error_class(
            f"{context} temporal layout cannot be empty."
        )

    if value not in SUPPORTED_INPUT_TEMPORAL_LAYOUTS:
        supported = ", ".join(
            SUPPORTED_INPUT_TEMPORAL_LAYOUTS
        )

        raise error_class(
            f"Unsupported {context.lower()} temporal layout. "
            f"Supported values: {supported}."
        )


# =========================================================
# Prepared Model Input
# =========================================================


@dataclass(frozen=True)
class ECGPreparedModelInput:
    """
    Fixed-shape twelve-lead ECG input ready for model inference.

    Unlike ECGAIInput from input_contract.py, this object must no
    longer contain missing samples.

    Each inner tuple represents one complete ECG lead.

    Lead order must match STANDARD_ECG_LEAD_NAMES exactly.

    Example conceptual shape:

        12 leads x N samples

    where N is identical for every lead.

    input_temporal_layout explicitly records what the twelve prepared
    lead arrays mean in time.

    Supported meanings:

        synchronous_12_lead
            All twelve leads correspond to the same source time
            interval.

        standard_3x4_sequential
            The prepared leads represent the supported sequential
            standard 3x4 print-layout semantics.

    This declaration is part of the inference contract. A model
    trained for one temporal layout must not silently consume the
    other.

    Resampling, interpolation, normalization, and source-window
    construction must happen before this object is created.
    """

    lead_names: tuple[str, ...]

    samples: tuple[
        tuple[float, ...],
        ...,
    ]

    sampling_frequency_hz: float

    preprocessing_version: str

    normalization_method: str

    input_temporal_layout: str

    def __post_init__(self):
        canonical_names = tuple(
            STANDARD_ECG_LEAD_NAMES
        )

        if self.lead_names != canonical_names:
            raise ECGModelInputError(
                "Prepared ECG model input must contain the "
                "canonical twelve ECG leads in canonical order."
            )

        if len(
            self.samples
        ) != 12:
            raise ECGModelInputError(
                "Prepared ECG model input must contain exactly "
                "twelve lead sample arrays."
            )

        try:
            sampling_frequency_hz = float(
                self.sampling_frequency_hz
            )
        except (
            TypeError,
            ValueError,
        ) as exc:
            raise ECGModelInputError(
                "ECG model sampling frequency must be a "
                "positive finite number."
            ) from exc

        if (
            not math.isfinite(
                sampling_frequency_hz
            )
            or sampling_frequency_hz <= 0
        ):
            raise ECGModelInputError(
                "ECG model sampling frequency must be a "
                "positive finite number."
            )

        if (
            not isinstance(
                self.preprocessing_version,
                str,
            )
            or not self.preprocessing_version.strip()
        ):
            raise ECGModelInputError(
                "A preprocessing version is required for "
                "ECG model input."
            )

        if (
            not isinstance(
                self.normalization_method,
                str,
            )
            or not self.normalization_method.strip()
        ):
            raise ECGModelInputError(
                "A normalization method is required for "
                "ECG model input."
            )

        _validate_input_temporal_layout(
            self.input_temporal_layout,
            error_class=ECGModelInputError,
            context="ECG model input",
        )

        expected_sample_count = None

        for (
            lead_index,
            lead_samples,
        ) in enumerate(
            self.samples
        ):
            lead_name = self.lead_names[
                lead_index
            ]

            if not lead_samples:
                raise ECGModelInputError(
                    "Prepared ECG lead "
                    f"{lead_name} contains no samples."
                )

            if expected_sample_count is None:
                expected_sample_count = len(
                    lead_samples
                )

            elif (
                len(
                    lead_samples
                )
                != expected_sample_count
            ):
                raise ECGModelInputError(
                    "All prepared ECG leads must contain "
                    "the same number of samples."
                )

            for sample_value in lead_samples:
                try:
                    numeric_value = float(
                        sample_value
                    )
                except (
                    TypeError,
                    ValueError,
                ) as exc:
                    raise ECGModelInputError(
                        "Prepared ECG lead "
                        f"{lead_name} contains a non-numeric sample."
                    ) from exc

                if not math.isfinite(
                    numeric_value
                ):
                    raise ECGModelInputError(
                        "Prepared ECG lead "
                        f"{lead_name} contains a non-finite sample."
                    )

    @property
    def lead_count(
        self,
    ) -> int:
        return len(
            self.samples
        )

    @property
    def sample_count(
        self,
    ) -> int:
        if not self.samples:
            return 0

        return len(
            self.samples[0]
        )

    @property
    def shape(
        self,
    ) -> tuple[int, int]:
        """
        Return the logical model-input shape:

            (lead_count, sample_count)
        """

        return (
            self.lead_count,
            self.sample_count,
        )

    @property
    def uses_sequential_print_layout(
        self,
    ) -> bool:
        """
        True when the prepared model tensor represents the supported
        sequential standard 3x4 print-layout semantics.
        """

        return (
            self.input_temporal_layout
            == INPUT_TEMPORAL_LAYOUT_STANDARD_3X4_SEQUENTIAL
        )


# =========================================================
# Model Metadata
# =========================================================


@dataclass(frozen=True)
class ECGModelMetadata:
    """
    Reproducibility and compatibility metadata for one trained
    ECG model artifact.

    labels:
        All output classes supported by the model.

    input_sampling_frequency_hz:
        Sampling frequency required by this model.

    input_sample_count:
        Number of samples required per ECG lead.

    preprocessing_version:
        Exact preprocessing contract used during model training.

    normalization_method:
        Exact normalization method used during model training.

        The prepared model input must declare the same method.

    input_temporal_layout:
        Exact temporal relationship used during model training.

        Examples:

            "synchronous_12_lead"

            "standard_3x4_sequential"

        This field is required because two tensors may have identical
        shape, sampling rate, and normalization while representing
        fundamentally different temporal relationships between leads.

    output_semantics:
        Description such as:

            "multilabel_probability"

            "multiclass_probability"

            "binary_probability"

    artifact_sha256:
        Optional future cryptographic fingerprint of the model
        artifact for traceability.
    """

    model_name: str

    model_version: str

    task: str

    framework: str

    labels: tuple[str, ...]

    input_sampling_frequency_hz: float

    input_sample_count: int

    preprocessing_version: str

    normalization_method: str

    input_temporal_layout: str

    output_semantics: str

    artifact_sha256: str = ""

    def __post_init__(self):
        if (
            not isinstance(
                self.model_name,
                str,
            )
            or not self.model_name.strip()
        ):
            raise ECGModelError(
                "ECG model name cannot be empty."
            )

        if (
            not isinstance(
                self.model_version,
                str,
            )
            or not self.model_version.strip()
        ):
            raise ECGModelError(
                "ECG model version cannot be empty."
            )

        if (
            not isinstance(
                self.task,
                str,
            )
            or not self.task.strip()
        ):
            raise ECGModelError(
                "ECG model task cannot be empty."
            )

        if (
            not isinstance(
                self.framework,
                str,
            )
            or not self.framework.strip()
        ):
            raise ECGModelError(
                "ECG model framework cannot be empty."
            )

        if not self.labels:
            raise ECGModelError(
                "ECG model metadata must declare at least "
                "one output label."
            )

        for label in self.labels:
            if (
                not isinstance(
                    label,
                    str,
                )
                or not label.strip()
            ):
                raise ECGModelError(
                    "ECG model labels cannot be empty."
                )

        if len(
            set(
                self.labels
            )
        ) != len(
            self.labels
        ):
            raise ECGModelError(
                "ECG model labels must be unique."
            )

        try:
            sampling_frequency_hz = float(
                self.input_sampling_frequency_hz
            )
        except (
            TypeError,
            ValueError,
        ) as exc:
            raise ECGModelError(
                "ECG model input sampling frequency must be "
                "a positive finite number."
            ) from exc

        if (
            not math.isfinite(
                sampling_frequency_hz
            )
            or sampling_frequency_hz <= 0
        ):
            raise ECGModelError(
                "ECG model input sampling frequency must be "
                "a positive finite number."
            )

        if (
            not isinstance(
                self.input_sample_count,
                int,
            )
            or isinstance(
                self.input_sample_count,
                bool,
            )
            or self.input_sample_count <= 0
        ):
            raise ECGModelError(
                "ECG model input sample count must be a "
                "positive integer."
            )

        if (
            not isinstance(
                self.preprocessing_version,
                str,
            )
            or not self.preprocessing_version.strip()
        ):
            raise ECGModelError(
                "ECG model preprocessing version cannot be empty."
            )

        if (
            not isinstance(
                self.normalization_method,
                str,
            )
            or not self.normalization_method.strip()
        ):
            raise ECGModelError(
                "ECG model normalization method cannot be empty."
            )

        _validate_input_temporal_layout(
            self.input_temporal_layout,
            error_class=ECGModelError,
            context="ECG model metadata",
        )

        if (
            not isinstance(
                self.output_semantics,
                str,
            )
            or not self.output_semantics.strip()
        ):
            raise ECGModelError(
                "ECG model output semantics cannot be empty."
            )


# =========================================================
# Structured Prediction Output
# =========================================================


@dataclass(frozen=True)
class ECGPredictionScore:
    """
    Output score for one ECG model class.

    score:
        Numeric model output constrained to [0, 1].

        Whether this represents a calibrated probability depends on
        the model metadata and validation performed during model
        development.

    selected:
        Whether the model's configured decision rule selected this
        class as a positive prediction.

    decision_threshold:
        Optional model threshold used for this label.
    """

    label: str

    score: float

    selected: bool

    decision_threshold: float | None = None

    def __post_init__(self):
        if (
            not isinstance(
                self.label,
                str,
            )
            or not self.label.strip()
        ):
            raise ECGModelOutputError(
                "ECG prediction label cannot be empty."
            )

        try:
            score = float(
                self.score
            )
        except (
            TypeError,
            ValueError,
        ) as exc:
            raise ECGModelOutputError(
                "ECG prediction score must be numeric."
            ) from exc

        if (
            not math.isfinite(
                score
            )
            or not 0.0 <= score <= 1.0
        ):
            raise ECGModelOutputError(
                "ECG prediction score must be a finite "
                "number between 0 and 1."
            )

        if not isinstance(
            self.selected,
            bool,
        ):
            raise ECGModelOutputError(
                "ECG prediction selected state must be boolean."
            )

        if self.decision_threshold is not None:
            try:
                threshold = float(
                    self.decision_threshold
                )
            except (
                TypeError,
                ValueError,
            ) as exc:
                raise ECGModelOutputError(
                    "ECG prediction decision threshold "
                    "must be numeric."
                ) from exc

            if (
                not math.isfinite(
                    threshold
                )
                or not 0.0 <= threshold <= 1.0
            ):
                raise ECGModelOutputError(
                    "ECG prediction decision threshold "
                    "must be between 0 and 1."
                )


@dataclass(frozen=True)
class ECGModelPrediction:
    """
    Structured output produced by one trained ECG model.

    This object is a model prediction only.

    It is NOT:
        - a final diagnosis,
        - a physician decision,
        - an XAI explanation,
        - proof of clinical validity.

    Multi-label models may return more than one selected label.
    """

    model_name: str

    model_version: str

    scores: tuple[
        ECGPredictionScore,
        ...,
    ]

    def __post_init__(self):
        if (
            not isinstance(
                self.model_name,
                str,
            )
            or not self.model_name.strip()
        ):
            raise ECGModelOutputError(
                "ECG prediction model name cannot be empty."
            )

        if (
            not isinstance(
                self.model_version,
                str,
            )
            or not self.model_version.strip()
        ):
            raise ECGModelOutputError(
                "ECG prediction model version cannot be empty."
            )

        if not self.scores:
            raise ECGModelOutputError(
                "ECG model prediction must contain at least "
                "one class score."
            )

        for score in self.scores:
            if not isinstance(
                score,
                ECGPredictionScore,
            ):
                raise ECGModelOutputError(
                    "ECG model prediction scores must be "
                    "ECGPredictionScore instances."
                )

        labels = tuple(
            score.label
            for score in self.scores
        )

        if len(
            set(
                labels
            )
        ) != len(
            labels
        ):
            raise ECGModelOutputError(
                "ECG model prediction contains duplicate labels."
            )

    @property
    def selected_labels(
        self,
    ) -> tuple[str, ...]:
        """
        Labels selected by the model's configured decision rule.
        """

        return tuple(
            score.label
            for score in self.scores
            if score.selected
        )

    @property
    def selected_count(
        self,
    ) -> int:
        return len(
            self.selected_labels
        )

    def get_score(
        self,
        label: str,
    ) -> ECGPredictionScore | None:
        """
        Return one class score by label.
        """

        for score in self.scores:
            if score.label == label:
                return score

        return None


# =========================================================
# Model Adapter Interface
# =========================================================


class ECGModelAdapter(ABC):
    """
    Abstract interface implemented by every trained ECG model backend.

    A future implementation may use:
        - scikit-learn,
        - ONNX Runtime,
        - PyTorch,
        - TensorFlow,
        - or another validated runtime.

    Application code should interact with trained ECG models through
    this interface rather than importing a model framework directly.

    validate_input() provides a strict compatibility gate between the
    prepared ECG tensor and the exact training contract declared by
    the model metadata.

    In particular, inference is rejected when two tensors have the
    same numerical shape but different temporal semantics.
    """

    @property
    @abstractmethod
    def metadata(
        self,
    ) -> ECGModelMetadata:
        """
        Return immutable metadata describing this model.
        """

        raise NotImplementedError

    @property
    @abstractmethod
    def is_ready(
        self,
    ) -> bool:
        """
        True only when the model artifact is loaded and ready
        for inference.
        """

        raise NotImplementedError

    @abstractmethod
    def load(
        self,
    ) -> None:
        """
        Load and validate the trained model artifact.

        Implementations should fail safely with ECGModelError when
        the artifact cannot be loaded or validated.
        """

        raise NotImplementedError

    @abstractmethod
    def _predict(
        self,
        model_input: ECGPreparedModelInput,
    ) -> ECGModelPrediction:
        """
        Framework-specific prediction implementation.

        Public callers should use predict() rather than calling
        this method directly.
        """

        raise NotImplementedError

    def validate_input(
        self,
        model_input: ECGPreparedModelInput,
    ) -> None:
        """
        Validate prepared ECG input against this model's declared
        training/inference requirements.

        Compatibility includes:
            - input type,
            - canonical twelve-lead order,
            - sample count,
            - sampling frequency,
            - preprocessing version,
            - normalization method,
            - temporal input layout.
        """

        if not isinstance(
            model_input,
            ECGPreparedModelInput,
        ):
            raise ECGModelInputError(
                "ECG model inference requires an "
                "ECGPreparedModelInput instance."
            )

        metadata = self.metadata

        if not isinstance(
            metadata,
            ECGModelMetadata,
        ):
            raise ECGModelError(
                "ECG model adapter metadata must be an "
                "ECGModelMetadata instance."
            )

        if (
            model_input.lead_names
            != tuple(
                STANDARD_ECG_LEAD_NAMES
            )
        ):
            raise ECGModelInputError(
                "ECG model input does not contain the canonical "
                "twelve-lead order."
            )

        if (
            model_input.sample_count
            != metadata.input_sample_count
        ):
            raise ECGModelInputError(
                "ECG model input sample count does not match "
                "the trained model requirement."
            )

        if not math.isclose(
            float(
                model_input.sampling_frequency_hz
            ),
            float(
                metadata.input_sampling_frequency_hz
            ),
            rel_tol=1e-9,
            abs_tol=1e-9,
        ):
            raise ECGModelInputError(
                "ECG model input sampling frequency does not match "
                "the trained model requirement."
            )

        if (
            model_input.preprocessing_version
            != metadata.preprocessing_version
        ):
            raise ECGModelInputError(
                "ECG preprocessing version does not match the "
                "version required by the trained model."
            )

        if (
            model_input.normalization_method
            != metadata.normalization_method
        ):
            raise ECGModelInputError(
                "ECG normalization method does not match the "
                "method required by the trained model."
            )

        if (
            model_input.input_temporal_layout
            != metadata.input_temporal_layout
        ):
            raise ECGModelInputError(
                "ECG input temporal layout does not match the "
                "layout required by the trained model."
            )

    def validate_prediction(
        self,
        prediction: ECGModelPrediction,
    ) -> None:
        """
        Validate a framework-specific prediction before exposing
        it to the rest of the application.
        """

        if not isinstance(
            prediction,
            ECGModelPrediction,
        ):
            raise ECGModelOutputError(
                "ECG model adapter returned an invalid "
                "prediction object."
            )

        metadata = self.metadata

        if not isinstance(
            metadata,
            ECGModelMetadata,
        ):
            raise ECGModelError(
                "ECG model adapter metadata must be an "
                "ECGModelMetadata instance."
            )

        if (
            prediction.model_name
            != metadata.model_name
        ):
            raise ECGModelOutputError(
                "ECG prediction model name does not match "
                "the adapter metadata."
            )

        if (
            prediction.model_version
            != metadata.model_version
        ):
            raise ECGModelOutputError(
                "ECG prediction model version does not match "
                "the adapter metadata."
            )

        prediction_labels = tuple(
            score.label
            for score in prediction.scores
        )

        if set(
            prediction_labels
        ) != set(
            metadata.labels
        ):
            raise ECGModelOutputError(
                "ECG prediction labels do not match the "
                "model metadata."
            )

    def predict(
        self,
        model_input: ECGPreparedModelInput,
    ) -> ECGModelPrediction:
        """
        Validate input, perform inference, and validate output.

        This is the public inference entry point for all ECG model
        adapters.

        The adapter must be ready before inference.

        Prepared data must satisfy the exact model contract,
        including temporal-layout compatibility.
        """

        if not self.is_ready:
            raise ECGModelNotReadyError(
                "The ECG model is not ready for inference."
            )

        self.validate_input(
            model_input
        )

        prediction = self._predict(
            model_input
        )

        self.validate_prediction(
            prediction
        )

        return prediction