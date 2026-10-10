"""

ECG AI model specification.



This module defines the explicit, reproducible specification required

before a trained ECG model can be connected to ClinicHub.



The specification is intentionally separate from:

    - ECG image processing,

    - signal calibration,

    - model preprocessing,

    - framework-specific model loading,

    - inference,

    - XAI,

    - physician review.



A model specification records the exact assumptions that must match

between model training and production inference.



Examples include:

    - model identity and version,

    - model task,

    - supported output labels,

    - sampling frequency,

    - samples per lead,

    - temporal relationship between the twelve leads,

    - preprocessing version,

    - normalization method,

    - missing-data policy,

    - decision thresholds,

    - output semantics,

    - optional model-artifact fingerprint.



No default clinical model is defined here.



This module does NOT:

    - choose a disease classification task,

    - choose ECG labels,

    - choose clinical thresholds,

    - choose sampling frequency,

    - choose signal duration,

    - assume a 2.5-second printed lead duration,

    - train a model,

    - load a model artifact,

    - perform inference,

    - generate XAI explanations,

    - produce a final clinical diagnosis.



Those values must come from the actual model-development and

validation process.

"""



from __future__ import annotations



import math

import string

from dataclasses import dataclass



from ecg.services.ai.model_interface import (

    ECGModelMetadata,

    INPUT_TEMPORAL_LAYOUT_STANDARD_3X4_SEQUENTIAL,

    INPUT_TEMPORAL_LAYOUT_SYNCHRONOUS_12_LEAD,

    SUPPORTED_INPUT_TEMPORAL_LAYOUTS,

)

from ecg.services.ai.preprocessing import (

    ECGPreprocessingConfig,

)

from ecg.services.lead_identification import (

    STANDARD_3X4_LEAD_LAYOUT,

    STANDARD_ECG_LEAD_NAMES,

)





# =========================================================

# Output Semantics

# =========================================================





OUTPUT_BINARY_PROBABILITY = "binary_probability"



OUTPUT_MULTICLASS_PROBABILITY = (

    "multiclass_probability"

)



OUTPUT_MULTILABEL_PROBABILITY = (

    "multilabel_probability"

)





SUPPORTED_OUTPUT_SEMANTICS = (

    OUTPUT_BINARY_PROBABILITY,

    OUTPUT_MULTICLASS_PROBABILITY,

    OUTPUT_MULTILABEL_PROBABILITY,

)





# The existing ClinicHub standard 3x4 layout is stored row-wise:

#

#     I    aVR   V1   V4

#     II   aVL   V2   V5

#     III  aVF   V3   V6

#

# For temporal reconstruction of a conventional sequential 3x4

# printout, the columns represent successive temporal segments.

#

# Therefore the temporal column groups are derived from the existing

# authoritative layout definition rather than duplicated manually.



STANDARD_3X4_SEQUENTIAL_COLUMNS = tuple(

    tuple(

        row[column_index]

        for row in STANDARD_3X4_LEAD_LAYOUT

    )

    for column_index in range(

        len(

            STANDARD_3X4_LEAD_LAYOUT[0]

        )

    )

)





# =========================================================

# Exceptions

# =========================================================





class ECGModelSpecificationError(ValueError):

    """

    Raised when an ECG model specification is incomplete,

    inconsistent, or unsafe to use.

    """





# =========================================================

# Label Specification

# =========================================================





@dataclass(frozen=True)

class ECGLabelSpecification:

    """

    Specification for one output label produced by an ECG model.



    name:

        Stable machine-readable label identifier.



        Examples might later include values such as:

            "normal"

            "atrial_fibrillation"



        This module intentionally does not define which labels the

        real model must support.



    display_name:

        Optional human-readable label.



        Clinical wording should be reviewed separately before being

        exposed to physicians or patients.



    decision_threshold:

        Optional model-specific threshold in the range [0, 1].



        Thresholds must come from model development and validation.

        This class does not select threshold values automatically.



        Multi-label probability models require an explicit threshold

        for every label.

    """



    name: str



    display_name: str = ""



    decision_threshold: float | None = None



    def __post_init__(self):

        if (

            not isinstance(

                self.name,

                str,

            )

            or not self.name.strip()

        ):

            raise ECGModelSpecificationError(

                "ECG model label name cannot be empty."

            )



        if (

            self.display_name

            and not self.display_name.strip()

        ):

            raise ECGModelSpecificationError(

                "ECG model label display name cannot contain "

                "only whitespace."

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

                raise ECGModelSpecificationError(

                    "ECG model decision threshold must be numeric."

                ) from exc



            if (

                not math.isfinite(

                    threshold

                )

                or not 0.0 <= threshold <= 1.0

            ):

                raise ECGModelSpecificationError(

                    "ECG model decision threshold must be a "

                    "finite number between 0 and 1."

                )





# =========================================================

# Lead Source Window

# =========================================================





@dataclass(frozen=True)

class ECGLeadSourceWindow:

    """

    Source-recording window used to construct one model lead.



    This object is primarily intended for reproducible dataset

    preparation.



    For synchronous twelve-lead recordings, every lead uses temporal

    segment zero and the same source interval.



    For a standard sequential 3x4 print-layout model, leads in the

    same printed column use the same source temporal segment.



    end_seconds_exclusive follows normal digital slicing semantics:



        [start_seconds, end_seconds_exclusive)



    This avoids confusing the source-window span N/Fs with the time

    difference between the first and final samples, which is

    (N - 1) / Fs.

    """



    lead_name: str



    temporal_segment_index: int



    start_seconds: float



    end_seconds_exclusive: float



    sample_count: int



    sampling_frequency_hz: float



    def __post_init__(self):

        if (

            not isinstance(

                self.lead_name,

                str,

            )

            or not self.lead_name.strip()

        ):

            raise ECGModelSpecificationError(

                "ECG lead source-window name cannot be empty."

            )



        if (

            not isinstance(

                self.temporal_segment_index,

                int,

            )

            or isinstance(

                self.temporal_segment_index,

                bool,

            )

            or self.temporal_segment_index < 0

        ):

            raise ECGModelSpecificationError(

                "ECG lead temporal segment index must be a "

                "non-negative integer."

            )



        try:

            start_seconds = float(

                self.start_seconds

            )



            end_seconds_exclusive = float(

                self.end_seconds_exclusive

            )

        except (

            TypeError,

            ValueError,

        ) as exc:

            raise ECGModelSpecificationError(

                "ECG lead source-window times must be numeric."

            ) from exc



        if (

            not math.isfinite(

                start_seconds

            )

            or start_seconds < 0.0

        ):

            raise ECGModelSpecificationError(

                "ECG lead source-window start must be a "

                "non-negative finite number."

            )



        if (

            not math.isfinite(

                end_seconds_exclusive

            )

            or end_seconds_exclusive

            <= start_seconds

        ):

            raise ECGModelSpecificationError(

                "ECG lead source-window end must be a finite "

                "number greater than its start."

            )



        if (

            not isinstance(

                self.sample_count,

                int,

            )

            or isinstance(

                self.sample_count,

                bool,

            )

            or self.sample_count < 1

        ):

            raise ECGModelSpecificationError(

                "ECG lead source-window sample count must be a "

                "positive integer."

            )



        try:

            sampling_frequency_hz = float(

                self.sampling_frequency_hz

            )

        except (

            TypeError,

            ValueError,

        ) as exc:

            raise ECGModelSpecificationError(

                "ECG lead source-window sampling frequency "

                "must be numeric."

            ) from exc



        if (

            not math.isfinite(

                sampling_frequency_hz

            )

            or sampling_frequency_hz <= 0.0

        ):

            raise ECGModelSpecificationError(

                "ECG lead source-window sampling frequency "

                "must be a positive finite number."

            )



    @property

    def span_seconds(

        self,

    ) -> float:

        """

        Exclusive source interval represented by the window.

        """



        return (

            float(

                self.end_seconds_exclusive

            )

            - float(

                self.start_seconds

            )

        )





# =========================================================

# Complete Model Specification

# =========================================================





@dataclass(frozen=True)

class ECGModelSpecification:

    """

    Complete reproducibility contract for one trained ECG model.



    The specification connects three important contracts:



        model-development specification

            ->

        ECGPreprocessingConfig

            ->

        ECGModelMetadata



    It also records how the twelve ECG leads relate in time.



    A model trained from synchronous digital twelve-lead ECGs must

    explicitly declare a synchronous temporal layout.



    A model trained to reproduce ClinicHub's supported sequential

    standard 3x4 printout must explicitly declare the

    standard_3x4_sequential temporal layout.



    Nothing in this class chooses clinical or model-specific values

    automatically.



    All model-specific values must come from the actual training and

    validation protocol.

    """



    # -----------------------------------------------------

    # Model identity

    # -----------------------------------------------------



    model_name: str



    model_version: str



    task: str



    framework: str



    # -----------------------------------------------------

    # Model outputs

    # -----------------------------------------------------



    labels: tuple[

        ECGLabelSpecification,

        ...,

    ]



    output_semantics: str



    # -----------------------------------------------------

    # Model input requirements

    # -----------------------------------------------------



    input_sampling_frequency_hz: float



    input_sample_count: int



    # -----------------------------------------------------

    # Temporal relationship between the twelve leads

    # -----------------------------------------------------



    input_temporal_layout: str



    # Required only for sequential standard 3x4 source construction.

    #

    # This is intentionally NOT assigned a default such as 2.5 s.

    #

    # The real value must come from the selected training protocol

    # and the print-layout assumptions being validated.

    source_column_duration_seconds: (

        float | None

    ) = None



    # -----------------------------------------------------

    # Preprocessing contract

    # -----------------------------------------------------



    preprocessing_version: str = ""



    normalization_method: str = ""



    missing_data_method: str = ""



    max_missing_fraction_per_lead: float = 0.0



    max_interpolation_gap_seconds: (

        float | None

    ) = None



    # Local starting offset inside the lead/window being prepared.

    #

    # For digitized print cells this is normally zero unless a

    # validated model intentionally uses a shorter sub-window.

    window_start_seconds: float = 0.0



    # -----------------------------------------------------

    # Artifact traceability

    # -----------------------------------------------------



    artifact_sha256: str = ""



    # -----------------------------------------------------

    # Optional documentation

    # -----------------------------------------------------



    description: str = ""



    def __post_init__(self):

        # -------------------------------------------------

        # Labels

        # -------------------------------------------------



        if not self.labels:

            raise ECGModelSpecificationError(

                "ECG model specification must contain at least "

                "one output label."

            )



        for label in self.labels:

            if not isinstance(

                label,

                ECGLabelSpecification,

            ):

                raise ECGModelSpecificationError(

                    "Every ECG model label must be an "

                    "ECGLabelSpecification instance."

                )



        label_names = tuple(

            label.name

            for label in self.labels

        )



        if len(

            set(

                label_names

            )

        ) != len(

            label_names

        ):

            raise ECGModelSpecificationError(

                "ECG model specification contains duplicate "

                "output labels."

            )



        # -------------------------------------------------

        # Output semantics

        # -------------------------------------------------



        if (

            self.output_semantics

            not in SUPPORTED_OUTPUT_SEMANTICS

        ):

            supported = ", ".join(

                SUPPORTED_OUTPUT_SEMANTICS

            )



            raise ECGModelSpecificationError(

                "Unsupported ECG model output semantics. "

                f"Supported values: {supported}."

            )



        # Multi-label prediction requires an explicit

        # per-label decision rule.

        if (

            self.output_semantics

            == OUTPUT_MULTILABEL_PROBABILITY

        ):

            missing_thresholds = tuple(

                label.name

                for label in self.labels

                if label.decision_threshold is None

            )



            if missing_thresholds:

                joined_names = ", ".join(

                    missing_thresholds

                )



                raise ECGModelSpecificationError(

                    "Multi-label ECG models require an explicit "

                    "decision threshold for every output label. "

                    "Missing thresholds: "

                    f"{joined_names}."

                )



        # -------------------------------------------------

        # Artifact fingerprint

        # -------------------------------------------------



        self._validate_artifact_sha256()



        # -------------------------------------------------

        # Validate the temporal-layout name before constructing

        # downstream contracts. This preserves clear specification-

        # level errors for blank or unsupported layout declarations.

        # -------------------------------------------------



        self._validate_input_temporal_layout_name()



        # -------------------------------------------------

        # Reuse existing preprocessing validation first.

        #

        # This validates sampling frequency, sample count,

        # normalization, missing-data configuration, local window

        # start, and the declared temporal-layout contract before

        # source-window calculations use them.

        # -------------------------------------------------



        try:

            self.to_preprocessing_config()

        except Exception as exc:

            if isinstance(

                exc,

                ECGModelSpecificationError,

            ):

                raise



            raise ECGModelSpecificationError(

                "ECG model preprocessing specification is invalid."

            ) from exc



        # -------------------------------------------------

        # Temporal input-layout validation

        # -------------------------------------------------



        self._validate_input_temporal_layout()



        # -------------------------------------------------

        # Reuse existing model-metadata validation

        # -------------------------------------------------



        try:

            self.to_model_metadata()

        except Exception as exc:

            if isinstance(

                exc,

                ECGModelSpecificationError,

            ):

                raise



            raise ECGModelSpecificationError(

                "ECG model metadata specification is invalid."

            ) from exc



    # =====================================================

    # Basic Properties

    # =====================================================



    @property

    def label_names(

        self,

    ) -> tuple[str, ...]:

        """

        Machine-readable labels in model-output order.

        """



        return tuple(

            label.name

            for label in self.labels

        )



    @property

    def label_count(

        self,

    ) -> int:

        return len(

            self.labels

        )



    @property

    def target_duration_seconds(

        self,

    ) -> float:

        """

        Time difference between first and final model samples.



        For N samples at sampling frequency Fs:



            duration = (N - 1) / Fs



        This is not the same as the exclusive digital window span.

        """



        return (

            (

                self.input_sample_count

                - 1

            )

            / float(

                self.input_sampling_frequency_hz

            )

        )



    @property

    def input_window_span_seconds(

        self,

    ) -> float:

        """

        Exclusive source-data span required for N samples.



        For N samples at sampling frequency Fs:



            span = N / Fs



        Example:

            1250 samples at 500 Hz occupy a 2.5-second digital

            source window, while the first-to-last sample time

            difference is 2.498 seconds.

        """



        return (

            float(

                self.input_sample_count

            )

            / float(

                self.input_sampling_frequency_hz

            )

        )



    @property

    def window_end_seconds(

        self,

    ) -> float:

        """

        Time of the final target sample relative to the local lead.

        """



        return (

            float(

                self.window_start_seconds

            )

            + self.target_duration_seconds

        )



    @property

    def window_end_seconds_exclusive(

        self,

    ) -> float:

        """

        Exclusive local source-window end used for digital slicing.

        """



        return (

            float(

                self.window_start_seconds

            )

            + self.input_window_span_seconds

        )



    @property

    def has_complete_thresholds(

        self,

    ) -> bool:

        """

        True only when every output label has an explicit

        decision threshold.

        """



        return all(

            label.decision_threshold

            is not None

            for label in self.labels

        )



    @property

    def decision_thresholds(

        self,

    ) -> tuple[

        tuple[

            str,

            float | None,

        ],

        ...,

    ]:

        """

        Return immutable label/threshold pairs.

        """



        return tuple(

            (

                label.name,

                label.decision_threshold,

            )

            for label in self.labels

        )



    @property

    def uses_sequential_print_layout(

        self,

    ) -> bool:

        return (

            self.input_temporal_layout

            == INPUT_TEMPORAL_LAYOUT_STANDARD_3X4_SEQUENTIAL

        )



    @property

    def source_temporal_segment_count(

        self,

    ) -> int:

        """

        Number of source temporal segments used to build one

        twelve-lead model input.



        Synchronous ECG:

            1 segment.



        Sequential standard 3x4 print layout:

            4 successive temporal segments.

        """



        if self.uses_sequential_print_layout:

            return len(

                STANDARD_3X4_SEQUENTIAL_COLUMNS

            )



        return 1



    @property

    def minimum_source_recording_span_seconds(

        self,

    ) -> float:

        """

        Minimum digital source-recording span needed to construct

        this model input.



        For synchronous input, all twelve leads use the same window.



        For sequential standard 3x4 input, four successive source

        columns are required.

        """



        if self.uses_sequential_print_layout:

            return (

                float(

                    self.source_column_duration_seconds

                )

                * self.source_temporal_segment_count

            )



        return self.window_end_seconds_exclusive



    @property

    def lead_source_windows(

        self,

    ) -> tuple[

        ECGLeadSourceWindow,

        ...,

    ]:

        """

        Return source windows for all twelve canonical ECG leads.



        Output order always follows STANDARD_ECG_LEAD_NAMES.

        """



        return tuple(

            self.source_window_for_lead(

                lead_name

            )

            for lead_name in STANDARD_ECG_LEAD_NAMES

        )



    # =====================================================

    # Label Lookup

    # =====================================================



    def get_label(

        self,

        name: str,

    ) -> ECGLabelSpecification | None:

        """

        Return one label specification by machine-readable name.

        """



        for label in self.labels:

            if label.name == name:

                return label



        return None



    def threshold_for(

        self,

        label_name: str,

    ) -> float | None:

        """

        Return the configured decision threshold for one label.



        Raises when the label does not belong to this model.

        """



        label = self.get_label(

            label_name

        )



        if label is None:

            raise ECGModelSpecificationError(

                "Unknown ECG model output label: "

                f"{label_name}."

            )



        return label.decision_threshold



    # =====================================================

    # Source Temporal Mapping

    # =====================================================



    def temporal_segment_for_lead(

        self,

        lead_name: str,

    ) -> int:

        """

        Return the source temporal segment used for one ECG lead.



        Synchronous twelve-lead input:

            every lead -> segment 0.



        Standard 3x4 sequential input:

            first print column  -> segment 0

            second print column -> segment 1

            third print column  -> segment 2

            fourth print column -> segment 3

        """



        if lead_name not in STANDARD_ECG_LEAD_NAMES:

            raise ECGModelSpecificationError(

                "Unknown canonical ECG lead: "

                f"{lead_name}."

            )



        if (

            self.input_temporal_layout

            == INPUT_TEMPORAL_LAYOUT_SYNCHRONOUS_12_LEAD

        ):

            return 0



        if (

            self.input_temporal_layout

            == INPUT_TEMPORAL_LAYOUT_STANDARD_3X4_SEQUENTIAL

        ):

            for (

                segment_index,

                column_leads,

            ) in enumerate(

                STANDARD_3X4_SEQUENTIAL_COLUMNS

            ):

                if lead_name in column_leads:

                    return segment_index



            raise ECGModelSpecificationError(

                "The standard 3x4 sequential layout does not "

                f"contain ECG lead {lead_name}."

            )



        raise ECGModelSpecificationError(

            "Unsupported ECG model temporal input layout."

        )



    def source_window_for_lead(

        self,

        lead_name: str,

    ) -> ECGLeadSourceWindow:

        """

        Return the exact source-recording interval used to construct

        one model lead.



        This is designed for training/validation dataset preparation

        so that digital ECG data can reproduce the temporal structure

        seen in ClinicHub's supported print layout.

        """



        temporal_segment_index = (

            self.temporal_segment_for_lead(

                lead_name

            )

        )



        if (

            self.input_temporal_layout

            == INPUT_TEMPORAL_LAYOUT_SYNCHRONOUS_12_LEAD

        ):

            segment_start_seconds = 0.0



        elif (

            self.input_temporal_layout

            == INPUT_TEMPORAL_LAYOUT_STANDARD_3X4_SEQUENTIAL

        ):

            segment_start_seconds = (

                temporal_segment_index

                * float(

                    self.source_column_duration_seconds

                )

            )



        else:

            raise ECGModelSpecificationError(

                "Unsupported ECG model temporal input layout."

            )



        source_start_seconds = (

            segment_start_seconds

            + float(

                self.window_start_seconds

            )

        )



        source_end_seconds_exclusive = (

            source_start_seconds

            + self.input_window_span_seconds

        )



        return ECGLeadSourceWindow(

            lead_name=lead_name,

            temporal_segment_index=(

                temporal_segment_index

            ),

            start_seconds=(

                source_start_seconds

            ),

            end_seconds_exclusive=(

                source_end_seconds_exclusive

            ),

            sample_count=(

                self.input_sample_count

            ),

            sampling_frequency_hz=(

                self.input_sampling_frequency_hz

            ),

        )



    # =====================================================

    # Contract Conversion

    # =====================================================



    def to_preprocessing_config(

        self,

    ) -> ECGPreprocessingConfig:

        """

        Build the exact runtime preprocessing configuration required

        by this model specification.



        At runtime, each already-extracted ClinicHub lead is expressed

        in its own local time coordinate system.



        ECGPreprocessingConfig carries the explicit temporal-layout

        declaration forward into ECGPreparedModelInput. The detailed

        sequential source-window mapping remains the responsibility of

        this specification and the training-data construction layer.

        """



        return ECGPreprocessingConfig(

            target_sampling_frequency_hz=(

                self.input_sampling_frequency_hz

            ),

            target_sample_count=(

                self.input_sample_count

            ),

            input_temporal_layout=(

                self.input_temporal_layout

            ),

            preprocessing_version=(

                self.preprocessing_version

            ),

            normalization_method=(

                self.normalization_method

            ),

            missing_data_method=(

                self.missing_data_method

            ),

            max_missing_fraction_per_lead=(

                self.max_missing_fraction_per_lead

            ),

            max_interpolation_gap_seconds=(

                self.max_interpolation_gap_seconds

            ),

            window_start_seconds=(

                self.window_start_seconds

            ),

        )



    def to_model_metadata(

        self,

    ) -> ECGModelMetadata:

        """

        Build immutable runtime metadata for the model adapter.



        ECGModelMetadata now carries the same temporal-layout

        declaration as this specification. The model adapter therefore

        rejects prepared input whose temporal semantics do not match

        the layout used during model training.

        """



        return ECGModelMetadata(

            model_name=(

                self.model_name

            ),

            model_version=(

                self.model_version

            ),

            task=(

                self.task

            ),

            framework=(

                self.framework

            ),

            labels=(

                self.label_names

            ),

            input_sampling_frequency_hz=(

                self.input_sampling_frequency_hz

            ),

            input_sample_count=(

                self.input_sample_count

            ),

            preprocessing_version=(

                self.preprocessing_version

            ),

            normalization_method=(

                self.normalization_method

            ),

            input_temporal_layout=(

                self.input_temporal_layout

            ),

            output_semantics=(

                self.output_semantics

            ),

            artifact_sha256=(

                self.artifact_sha256

            ),

        )



    # =====================================================

    # Temporal Layout Validation

    # =====================================================



    def _validate_input_temporal_layout_name(

        self,

    ) -> None:

        """
        Validate only the temporal-layout declaration itself.

        This check runs before preprocessing-contract construction so
        blank or unsupported layout names fail with a clear
        ECGModelSpecificationError rather than being hidden behind a
        downstream contract-conversion error.
        """



        if (

            not isinstance(

                self.input_temporal_layout,

                str,

            )

            or not self.input_temporal_layout.strip()

        ):

            raise ECGModelSpecificationError(

                "ECG model input temporal layout cannot be empty."

            )



        if (

            self.input_temporal_layout

            not in SUPPORTED_INPUT_TEMPORAL_LAYOUTS

        ):

            supported = ", ".join(

                SUPPORTED_INPUT_TEMPORAL_LAYOUTS

            )



            raise ECGModelSpecificationError(

                "Unsupported ECG model input temporal layout. "

                f"Supported values: {supported}."

            )



    def _validate_input_temporal_layout(

        self,

    ) -> None:

        """

        Validate temporal assumptions independently from clinical

        model choices.

        """



        self._validate_input_temporal_layout_name()



        if (

            self.input_temporal_layout

            == INPUT_TEMPORAL_LAYOUT_SYNCHRONOUS_12_LEAD

        ):

            if (

                self.source_column_duration_seconds

                is not None

            ):

                raise ECGModelSpecificationError(

                    "Synchronous twelve-lead ECG models must not "

                    "define a sequential source-column duration."

                )



            return



        # -------------------------------------------------

        # Standard 3x4 sequential layout

        # -------------------------------------------------



        if (

            self.input_temporal_layout

            == INPUT_TEMPORAL_LAYOUT_STANDARD_3X4_SEQUENTIAL

        ):

            if (

                self.source_column_duration_seconds

                is None

            ):

                raise ECGModelSpecificationError(

                    "Standard 3x4 sequential ECG models require "

                    "an explicit source-column duration."

                )



            try:

                source_column_duration_seconds = float(

                    self.source_column_duration_seconds

                )

            except (

                TypeError,

                ValueError,

            ) as exc:

                raise ECGModelSpecificationError(

                    "ECG source-column duration must be numeric."

                ) from exc



            if (

                not math.isfinite(

                    source_column_duration_seconds

                )

                or source_column_duration_seconds <= 0.0

            ):

                raise ECGModelSpecificationError(

                    "ECG source-column duration must be a "

                    "positive finite number."

                )



            # The selected local model window must fit completely

            # inside one sequential print column. This prevents a

            # training window from silently spilling into the next

            # print-layout time segment.

            if (

                self.window_end_seconds_exclusive

                > source_column_duration_seconds

                + 1e-12

            ):

                raise ECGModelSpecificationError(

                    "The ECG model input window does not fit "

                    "inside one standard 3x4 source column."

                )



            # Defensive structural check: the temporal-column mapping

            # must still represent exactly the canonical twelve leads.

            mapped_leads = tuple(

                lead_name

                for column_leads

                in STANDARD_3X4_SEQUENTIAL_COLUMNS

                for lead_name in column_leads

            )



            if (

                len(

                    mapped_leads

                )

                != len(

                    STANDARD_ECG_LEAD_NAMES

                )

                or set(

                    mapped_leads

                )

                != set(

                    STANDARD_ECG_LEAD_NAMES

                )

            ):

                raise ECGModelSpecificationError(

                    "The standard 3x4 temporal mapping does not "

                    "contain exactly the canonical twelve ECG leads."

                )



            return



        raise ECGModelSpecificationError(

            "Unsupported ECG model input temporal layout."

        )



    # =====================================================

    # Artifact Validation

    # =====================================================



    def _validate_artifact_sha256(

        self,

    ) -> None:

        """

        Validate an optional SHA-256 model-artifact fingerprint.



        Empty is allowed before a trained artifact exists.



        Once supplied, the fingerprint must contain exactly

        64 hexadecimal characters.

        """



        if not self.artifact_sha256:

            return



        fingerprint = (

            self.artifact_sha256.strip()

        )



        if len(

            fingerprint

        ) != 64:

            raise ECGModelSpecificationError(

                "ECG model artifact SHA-256 fingerprint must "

                "contain exactly 64 hexadecimal characters."

            )



        hexadecimal_characters = set(

            string.hexdigits

        )



        if any(

            character

            not in hexadecimal_characters

            for character in fingerprint

        ):

            raise ECGModelSpecificationError(

                "ECG model artifact SHA-256 fingerprint must "

                "contain only hexadecimal characters."

            )
