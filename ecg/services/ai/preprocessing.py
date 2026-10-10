"""

ECG AI model preprocessing.



This module converts the calibrated twelve-lead ECG contract produced

by input_contract.py into a fixed-shape ECGPreparedModelInput suitable

for a trained model adapter.



Pipeline position:



    ECG image/file

        ->

    image/signal processing

        ->

    ECGAIInput

        ->

    this preprocessing layer

        ->

    ECGPreparedModelInput

        ->

    trained ECG model adapter



Responsibilities:

    - Validate calibrated twelve-lead ECG input.

    - Enforce a model-specific time window.

    - Handle missing samples only through an explicit policy.

    - Resample each lead onto a fixed uniform time grid.

    - Apply an explicitly selected normalization strategy.

    - Preserve an explicit twelve-lead temporal-layout declaration.

    - Produce fixed-shape finite model input.



This module does NOT:

    - Choose clinical thresholds.

    - Choose a sampling frequency automatically.

    - Choose a signal duration automatically.

    - Diagnose ECG abnormalities.

    - Run model inference.

    - Produce XAI explanations.

    - Replace physician review.



The exact preprocessing configuration, including temporal-layout

semantics, must match the configuration used during model training.

"""



from __future__ import annotations



import math

from dataclasses import dataclass



import numpy as np



from ecg.services.ai.input_contract import (

    ECGAIInput,

    ECGAILeadInput,

)

from ecg.services.ai.model_interface import (

    ECGPreparedModelInput,

    SUPPORTED_INPUT_TEMPORAL_LAYOUTS,

)

from ecg.services.lead_identification import (

    STANDARD_ECG_LEAD_NAMES,

)





# =========================================================

# Constants

# =========================================================





MISSING_DATA_REJECT = "reject"

MISSING_DATA_LINEAR_INTERPOLATION = "linear_interpolation"



SUPPORTED_MISSING_DATA_METHODS = (

    MISSING_DATA_REJECT,

    MISSING_DATA_LINEAR_INTERPOLATION,

)





NORMALIZATION_NONE = "none"

NORMALIZATION_ZSCORE_PER_LEAD = "zscore_per_lead"



SUPPORTED_NORMALIZATION_METHODS = (

    NORMALIZATION_NONE,

    NORMALIZATION_ZSCORE_PER_LEAD,

)





# Small numerical tolerance used only for time-boundary comparisons.

_TIME_TOLERANCE_SECONDS = 1e-9



# Prevent division by an effectively zero standard deviation.

_MIN_STANDARD_DEVIATION = 1e-12





# =========================================================

# Exceptions

# =========================================================





class ECGPreprocessingError(ValueError):

    """

    Raised when calibrated ECG data cannot safely be converted

    into fixed-shape model input.

    """





# =========================================================

# Configuration

# =========================================================





@dataclass(frozen=True)

class ECGPreprocessingConfig:

    """

    Explicit preprocessing configuration for one trained ECG model.



    target_sampling_frequency_hz:

        Sampling frequency required by the trained model.



    target_sample_count:

        Number of samples required per lead.



    preprocessing_version:

        Immutable identifier for this complete preprocessing recipe.

        A trained model must declare the same version.



    input_temporal_layout:

        Explicit temporal relationship represented by the twelve leads.

        Supported values are defined by model_interface.py.

        This layer does not infer temporal semantics from tensor shape.

        The declared layout must match the layout used during model
        training and later declared by the model metadata.



    normalization_method:

        One of:

            - "none"

            - "zscore_per_lead"



        This choice must match model training.



    missing_data_method:

        "reject":

            Any missing calibrated amplitude causes preprocessing

            to fail.



        "linear_interpolation":

            Internal missing values may be interpolated only when

            both the total missing fraction and maximum interpolation

            gap satisfy explicit configured limits.



    max_missing_fraction_per_lead:

        Maximum fraction of missing source samples permitted for

        linear interpolation.



        This value is not a clinical threshold. It is a model-specific

        preprocessing constraint and must be chosen during model

        development.



    max_interpolation_gap_seconds:

        Maximum duration of any internal missing-data gap that may

        be bridged when linear interpolation is enabled.



        This must be explicitly supplied for linear interpolation.



    window_start_seconds:

        Start of the source signal window used for model input.



        The default is zero seconds. The requested model window must

        be fully covered by valid source data; extrapolation is not

        permitted.

    """



    target_sampling_frequency_hz: float

    target_sample_count: int



    preprocessing_version: str



    input_temporal_layout: str



    normalization_method: str = (

        NORMALIZATION_NONE

    )



    missing_data_method: str = (

        MISSING_DATA_REJECT

    )



    max_missing_fraction_per_lead: float = 0.0



    max_interpolation_gap_seconds: (

        float | None

    ) = None



    window_start_seconds: float = 0.0



    def __post_init__(self):

        # -------------------------------------------------

        # Sampling frequency

        # -------------------------------------------------



        try:

            sampling_frequency = float(

                self.target_sampling_frequency_hz

            )

        except (

            TypeError,

            ValueError,

        ) as exc:

            raise ECGPreprocessingError(

                "Target ECG sampling frequency must be a "

                "positive finite number."

            ) from exc



        if (

            not math.isfinite(

                sampling_frequency

            )

            or sampling_frequency <= 0

        ):

            raise ECGPreprocessingError(

                "Target ECG sampling frequency must be a "

                "positive finite number."

            )



        # -------------------------------------------------

        # Sample count

        # -------------------------------------------------



        if (

            not isinstance(

                self.target_sample_count,

                int,

            )

            or isinstance(

                self.target_sample_count,

                bool,

            )

            or self.target_sample_count <= 1

        ):

            raise ECGPreprocessingError(

                "Target ECG sample count must be an integer "

                "greater than one."

            )



        # -------------------------------------------------

        # Version

        # -------------------------------------------------



        if (

            not isinstance(

                self.preprocessing_version,

                str,

            )

            or not self.preprocessing_version.strip()

        ):

            raise ECGPreprocessingError(

                "An ECG preprocessing version is required."

            )



        # -------------------------------------------------

        # Temporal input layout

        # -------------------------------------------------



        if (

            not isinstance(

                self.input_temporal_layout,

                str,

            )

            or not self.input_temporal_layout.strip()

        ):

            raise ECGPreprocessingError(

                "An ECG input temporal layout is required."

            )



        if (

            self.input_temporal_layout

            not in SUPPORTED_INPUT_TEMPORAL_LAYOUTS

        ):

            supported = ", ".join(

                SUPPORTED_INPUT_TEMPORAL_LAYOUTS

            )



            raise ECGPreprocessingError(

                "Unsupported ECG input temporal layout. "

                f"Supported layouts: {supported}."

            )



        # -------------------------------------------------

        # Normalization

        # -------------------------------------------------



        if (

            self.normalization_method

            not in SUPPORTED_NORMALIZATION_METHODS

        ):

            supported = ", ".join(

                SUPPORTED_NORMALIZATION_METHODS

            )



            raise ECGPreprocessingError(

                "Unsupported ECG normalization method. "

                f"Supported methods: {supported}."

            )



        # -------------------------------------------------

        # Missing-data strategy

        # -------------------------------------------------



        if (

            self.missing_data_method

            not in SUPPORTED_MISSING_DATA_METHODS

        ):

            supported = ", ".join(

                SUPPORTED_MISSING_DATA_METHODS

            )



            raise ECGPreprocessingError(

                "Unsupported ECG missing-data method. "

                f"Supported methods: {supported}."

            )



        try:

            missing_fraction = float(

                self.max_missing_fraction_per_lead

            )

        except (

            TypeError,

            ValueError,

        ) as exc:

            raise ECGPreprocessingError(

                "Maximum ECG missing fraction must be a "

                "finite number between 0 and 1."

            ) from exc



        if (

            not math.isfinite(

                missing_fraction

            )

            or not 0.0 <= missing_fraction <= 1.0

        ):

            raise ECGPreprocessingError(

                "Maximum ECG missing fraction must be a "

                "finite number between 0 and 1."

            )



        if (

            self.missing_data_method

            == MISSING_DATA_REJECT

            and missing_fraction != 0.0

        ):

            raise ECGPreprocessingError(

                "Maximum missing fraction must be zero when "

                "the ECG missing-data method is 'reject'."

            )



        if (

            self.missing_data_method

            == MISSING_DATA_LINEAR_INTERPOLATION

        ):

            if (

                self.max_interpolation_gap_seconds

                is None

            ):

                raise ECGPreprocessingError(

                    "Linear ECG interpolation requires an "

                    "explicit maximum interpolation gap."

                )



            try:

                max_gap = float(

                    self.max_interpolation_gap_seconds

                )

            except (

                TypeError,

                ValueError,

            ) as exc:

                raise ECGPreprocessingError(

                    "Maximum ECG interpolation gap must be "

                    "a positive finite number."

                ) from exc



            if (

                not math.isfinite(

                    max_gap

                )

                or max_gap <= 0

            ):

                raise ECGPreprocessingError(

                    "Maximum ECG interpolation gap must be "

                    "a positive finite number."

                )



        # -------------------------------------------------

        # Window start

        # -------------------------------------------------



        try:

            window_start = float(

                self.window_start_seconds

            )

        except (

            TypeError,

            ValueError,

        ) as exc:

            raise ECGPreprocessingError(

                "ECG model window start must be a "

                "non-negative finite number."

            ) from exc



        if (

            not math.isfinite(

                window_start

            )

            or window_start < 0

        ):

            raise ECGPreprocessingError(

                "ECG model window start must be a "

                "non-negative finite number."

            )



    @property

    def target_duration_seconds(self) -> float:

        """

        Duration between the first and last model sample.



        For N samples at Fs:



            duration = (N - 1) / Fs

        """



        return (

            (

                self.target_sample_count

                - 1

            )

            / float(

                self.target_sampling_frequency_hz

            )

        )



    @property

    def window_end_seconds(self) -> float:

        return (

            float(

                self.window_start_seconds

            )

            + self.target_duration_seconds

        )





# =========================================================

# Internal Validation Helpers

# =========================================================





def _validate_ai_input(

    ai_input: ECGAIInput,

) -> None:

    """

    Validate the calibrated input before model preprocessing.

    """



    if not isinstance(

        ai_input,

        ECGAIInput,

    ):

        raise ECGPreprocessingError(

            "ECG preprocessing requires an ECGAIInput instance."

        )



    if not ai_input.complete_12_lead:

        raise ECGPreprocessingError(

            "ECG preprocessing requires the complete canonical "

            "twelve-lead ECG set."

        )



    if (

        ai_input.lead_names

        != tuple(

            STANDARD_ECG_LEAD_NAMES

        )

    ):

        raise ECGPreprocessingError(

            "ECG preprocessing requires canonical twelve-lead order."

        )





def _validate_lead_signal(

    lead: ECGAILeadInput,

) -> None:

    """

    Validate one calibrated lead's raw time/amplitude representation.

    """



    if not lead.time_seconds:

        raise ECGPreprocessingError(

            f"ECG lead {lead.name} contains no time samples."

        )



    if not lead.amplitude_mv:

        raise ECGPreprocessingError(

            f"ECG lead {lead.name} contains no amplitude samples."

        )



    if (

        len(

            lead.time_seconds

        )

        != len(

            lead.amplitude_mv

        )

    ):

        raise ECGPreprocessingError(

            f"ECG lead {lead.name} contains inconsistent "

            "time and amplitude lengths."

        )



    previous_time = None



    for value in lead.time_seconds:

        try:

            numeric_time = float(

                value

            )

        except (

            TypeError,

            ValueError,

        ) as exc:

            raise ECGPreprocessingError(

                f"ECG lead {lead.name} contains a non-numeric "

                "time value."

            ) from exc



        if not math.isfinite(

            numeric_time

        ):

            raise ECGPreprocessingError(

                f"ECG lead {lead.name} contains a non-finite "

                "time value."

            )



        if (

            previous_time is not None

            and numeric_time <= previous_time

        ):

            raise ECGPreprocessingError(

                f"ECG lead {lead.name} time values must be "

                "strictly increasing."

            )



        previous_time = numeric_time



    for value in lead.amplitude_mv:

        if value is None:

            continue



        try:

            numeric_value = float(

                value

            )

        except (

            TypeError,

            ValueError,

        ) as exc:

            raise ECGPreprocessingError(

                f"ECG lead {lead.name} contains a non-numeric "

                "amplitude value."

            ) from exc



        if not math.isfinite(

            numeric_value

        ):

            raise ECGPreprocessingError(

                f"ECG lead {lead.name} contains a non-finite "

                "amplitude value."

            )





# =========================================================

# Missing-Data Helpers

# =========================================================





def _missing_fraction(

    lead: ECGAILeadInput,

) -> float:

    total_count = len(

        lead.amplitude_mv

    )



    if total_count == 0:

        return 1.0



    missing_count = sum(

        value is None

        for value in lead.amplitude_mv

    )



    return (

        missing_count

        / total_count

    )





def _internal_missing_gap_durations(

    lead: ECGAILeadInput,

) -> tuple[float, ...]:

    """

    Return durations of internal missing-data regions.



    Edge missing values are rejected elsewhere because model

    preprocessing never extrapolates signal amplitudes.

    """



    times = tuple(

        float(

            value

        )

        for value in lead.time_seconds

    )



    amplitudes = lead.amplitude_mv



    gap_durations = []



    index = 0



    while index < len(

        amplitudes

    ):

        if amplitudes[index] is not None:

            index += 1

            continue



        gap_start = index



        while (

            index < len(

                amplitudes

            )

            and amplitudes[index] is None

        ):

            index += 1



        gap_end = index - 1



        # Missing data at either edge would require extrapolation.

        if (

            gap_start == 0

            or gap_end

            == len(

                amplitudes

            ) - 1

        ):

            raise ECGPreprocessingError(

                f"ECG lead {lead.name} contains missing samples "

                "at the signal boundary; extrapolation is not allowed."

            )



        left_valid_index = (

            gap_start - 1

        )



        right_valid_index = (

            gap_end + 1

        )



        gap_duration = (

            times[

                right_valid_index

            ]

            - times[

                left_valid_index

            ]

        )



        gap_durations.append(

            float(

                gap_duration

            )

        )



    return tuple(

        gap_durations

    )





def _prepare_valid_source_points(

    lead: ECGAILeadInput,

    config: ECGPreprocessingConfig,

) -> tuple[

    np.ndarray,

    np.ndarray,

]:

    """

    Return finite source time/amplitude arrays according to the

    configured missing-data policy.

    """



    _validate_lead_signal(

        lead

    )



    missing_fraction = (

        _missing_fraction(

            lead

        )

    )



    if (

        config.missing_data_method

        == MISSING_DATA_REJECT

    ):

        if missing_fraction > 0:

            raise ECGPreprocessingError(

                f"ECG lead {lead.name} contains missing samples "

                "and the configured preprocessing policy rejects "

                "missing data."

            )



    elif (

        config.missing_data_method

        == MISSING_DATA_LINEAR_INTERPOLATION

    ):

        if (

            missing_fraction

            > float(

                config.max_missing_fraction_per_lead

            )

        ):

            raise ECGPreprocessingError(

                f"ECG lead {lead.name} exceeds the configured "

                "maximum missing-sample fraction."

            )



        if missing_fraction > 0:

            gap_durations = (

                _internal_missing_gap_durations(

                    lead

                )

            )



            max_allowed_gap = float(

                config.max_interpolation_gap_seconds

            )



            for gap_duration in gap_durations:

                if (

                    gap_duration

                    > max_allowed_gap

                    + _TIME_TOLERANCE_SECONDS

                ):

                    raise ECGPreprocessingError(

                        f"ECG lead {lead.name} contains a missing-data "

                        "gap larger than the configured interpolation "

                        "limit."

                    )



    source_times = []

    source_amplitudes = []



    for (

        time_value,

        amplitude_value,

    ) in zip(

        lead.time_seconds,

        lead.amplitude_mv,

        strict=True,

    ):

        if amplitude_value is None:

            continue



        source_times.append(

            float(

                time_value

            )

        )



        source_amplitudes.append(

            float(

                amplitude_value

            )

        )



    if len(

        source_times

    ) < 2:

        raise ECGPreprocessingError(

            f"ECG lead {lead.name} does not contain enough "

            "valid samples for model preprocessing."

        )



    return (

        np.asarray(

            source_times,

            dtype=np.float64,

        ),

        np.asarray(

            source_amplitudes,

            dtype=np.float64,

        ),

    )





# =========================================================

# Resampling

# =========================================================





def _build_target_time_grid(

    config: ECGPreprocessingConfig,

) -> np.ndarray:

    """

    Build the exact uniform model time grid.

    """



    sampling_frequency = float(

        config.target_sampling_frequency_hz

    )



    sample_indices = np.arange(

        config.target_sample_count,

        dtype=np.float64,

    )



    return (

        float(

            config.window_start_seconds

        )

        + (

            sample_indices

            / sampling_frequency

        )

    )





def _resample_lead(

    lead: ECGAILeadInput,

    config: ECGPreprocessingConfig,

    target_times: np.ndarray,

) -> np.ndarray:

    """

    Resample one calibrated ECG lead onto the uniform model grid.



    np.interp performs linear interpolation between valid source

    samples.



    Extrapolation is explicitly prevented by checking source coverage

    before interpolation.

    """



    (

        source_times,

        source_amplitudes,

    ) = _prepare_valid_source_points(

        lead,

        config,

    )



    target_start = float(

        target_times[0]

    )



    target_end = float(

        target_times[-1]

    )



    source_start = float(

        source_times[0]

    )



    source_end = float(

        source_times[-1]

    )



    if (

        source_start

        > target_start

        + _TIME_TOLERANCE_SECONDS

    ):

        raise ECGPreprocessingError(

            f"ECG lead {lead.name} does not contain valid data "

            "at the beginning of the requested model window."

        )



    if (

        source_end

        < target_end

        - _TIME_TOLERANCE_SECONDS

    ):

        raise ECGPreprocessingError(

            f"ECG lead {lead.name} is shorter than the requested "

            "model input window."

        )



    resampled = np.interp(

        target_times,

        source_times,

        source_amplitudes,

    )



    if (

        resampled.shape

        != (

            config.target_sample_count,

        )

    ):

        raise ECGPreprocessingError(

            f"ECG lead {lead.name} could not be resampled "

            "to the requested model shape."

        )



    if not np.all(

        np.isfinite(

            resampled

        )

    ):

        raise ECGPreprocessingError(

            f"ECG lead {lead.name} produced non-finite "

            "values during resampling."

        )



    return resampled.astype(

        np.float64,

        copy=False,

    )





# =========================================================

# Normalization

# =========================================================





def _normalize_lead(

    lead_name: str,

    samples: np.ndarray,

    config: ECGPreprocessingConfig,

) -> np.ndarray:

    """

    Apply the explicitly configured normalization strategy.

    """



    if (

        config.normalization_method

        == NORMALIZATION_NONE

    ):

        normalized = samples.copy()



    elif (

        config.normalization_method

        == NORMALIZATION_ZSCORE_PER_LEAD

    ):

        mean = float(

            np.mean(

                samples

            )

        )



        standard_deviation = float(

            np.std(

                samples,

                ddof=0,

            )

        )



        if (

            not math.isfinite(

                mean

            )

            or not math.isfinite(

                standard_deviation

            )

        ):

            raise ECGPreprocessingError(

                f"ECG lead {lead_name} produced invalid "

                "normalization statistics."

            )



        if (

            standard_deviation

            <= _MIN_STANDARD_DEVIATION

        ):

            raise ECGPreprocessingError(

                f"ECG lead {lead_name} cannot be z-score "

                "normalized because its standard deviation "

                "is effectively zero."

            )



        normalized = (

            samples - mean

        ) / standard_deviation



    else:

        # Defensive branch. Configuration validation should

        # already prevent reaching this point.

        raise ECGPreprocessingError(

            "Unsupported ECG normalization method."

        )



    if not np.all(

        np.isfinite(

            normalized

        )

    ):

        raise ECGPreprocessingError(

            f"ECG lead {lead_name} contains non-finite values "

            "after normalization."

        )



    return normalized.astype(

        np.float64,

        copy=False,

    )





# =========================================================

# Public Preprocessing Entry Point

# =========================================================





def prepare_ecg_model_input(

    ai_input: ECGAIInput,

    config: ECGPreprocessingConfig,

) -> ECGPreparedModelInput:

    """

    Convert calibrated twelve-lead ECG data into fixed-shape model input.



    Processing order:



        1. Validate ECGAIInput.

        2. Validate preprocessing configuration.

        3. Enforce missing-data policy independently for each lead.

        4. Create a fixed uniform target time grid.

        5. Resample every canonical ECG lead.

        6. Apply the configured normalization.

        7. Construct ECGPreparedModelInput.



    The function never chooses model parameters automatically.



    target_sampling_frequency_hz, target_sample_count,

    preprocessing_version, input temporal layout, normalization method,

    and any interpolation policy must come from the

    model-development/training specification.

    """



    _validate_ai_input(

        ai_input

    )



    if not isinstance(

        config,

        ECGPreprocessingConfig,

    ):

        raise ECGPreprocessingError(

            "ECG preprocessing requires an "

            "ECGPreprocessingConfig instance."

        )



    target_times = (

        _build_target_time_grid(

            config

        )

    )



    lead_by_name = {

        lead.name: lead

        for lead in ai_input.leads

    }



    prepared_samples = []



    for lead_name in STANDARD_ECG_LEAD_NAMES:

        lead = lead_by_name.get(

            lead_name

        )



        if lead is None:

            raise ECGPreprocessingError(

                "A required ECG lead is missing during model "

                f"preprocessing: {lead_name}."

            )



        resampled = _resample_lead(

            lead,

            config,

            target_times,

        )



        normalized = _normalize_lead(

            lead_name,

            resampled,

            config,

        )



        prepared_samples.append(

            tuple(

                float(

                    value

                )

                for value in normalized

            )

        )



    return ECGPreparedModelInput(

        lead_names=tuple(

            STANDARD_ECG_LEAD_NAMES

        ),

        samples=tuple(

            prepared_samples

        ),

        sampling_frequency_hz=float(

            config.target_sampling_frequency_hz

        ),

        preprocessing_version=(

            config.preprocessing_version

        ),

        normalization_method=(

            config.normalization_method

        ),

        input_temporal_layout=(

            config.input_temporal_layout

        ),

    )
