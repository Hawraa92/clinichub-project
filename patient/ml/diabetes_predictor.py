# patient/ml/diabetes_predictor.py
from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import joblib
import numpy as np
from django.conf import settings

try:
    import pandas as pd  # optional
except Exception:  # pragma: no cover
    pd = None  # type: ignore


# -------------------------------------------------------------------
# Configuration
# -------------------------------------------------------------------
DEFAULT_FEATURES: List[str] = [
    "HighBP", "HighChol", "CholCheck", "BMI", "Smoker", "Stroke",
    "HeartDiseaseorAttack", "PhysActivity", "Fruits", "Veggies",
    "HvyAlcoholConsump", "AnyHealthcare", "NoDocbcCost", "GenHlth",
    "MentHlth", "PhysHlth", "DiffWalk", "Sex", "Age", "Education", "Income",
]

# System convention across the app:
# 0 = Healthy, 1 = Prediabetic, 2 = Diabetic
# If the loaded model is binary (2 classes), we map:
#   NEGATIVE -> system "0"
#   POSITIVE -> system "2"
SYSTEM_HEALTHY = 0
SYSTEM_PREDIABETIC = 1
SYSTEM_DIABETIC = 2

# Screening thresholds (NOT diagnosis).
# risk_score = P(diabetic) + 0.5 * P(prediabetic)
DEFAULT_RISK_MEDIUM = float(getattr(settings, "DIABETES_RISK_MEDIUM", 0.212))
DEFAULT_RISK_HIGH = float(getattr(settings, "DIABETES_RISK_HIGH", 0.35))


@dataclass(frozen=True)
class DiabetesPrediction:
    """
    predicted_class:
        - multiclass model: 0/1/2
        - binary model: 0/2 (POS mapped to 2)
    proba:
        Always {"0": p0, "1": p1, "2": p2}.
        For binary models: "1" remains 0.0 (model has no prediabetic class).
    diabetic_probability:
        proba["2"] under system mapping.
    risk_score:
        P(diabetic) + 0.5*P(prediabetic) (binary => == P(diabetic))
    """
    predicted_class: int
    predicted_label: str
    proba: Dict[str, float]
    diabetic_probability: float
    risk_score: float
    risk_level: str
    recommendation: str
    features_used: List[str]


# -------------------------------------------------------------------
# Model path + loading
# -------------------------------------------------------------------
def _candidate_model_paths() -> List[Path]:
    """
    Supported layouts:
    1) settings.DIABETES_MODEL_PATH or env DIABETES_MODEL_PATH
    2) patient/ml/diabetes_{MODEL_NAME}.(joblib|gz|pkl)
    3) BASE_DIR/ml/artifacts/<MODEL_FILENAME>
    4) BASE_DIR/ml/<MODEL_FILENAME>
    """
    explicit_path = os.getenv("DIABETES_MODEL_PATH", getattr(settings, "DIABETES_MODEL_PATH", None))
    if explicit_path:
        return [Path(explicit_path).expanduser().resolve()]

    model_name = os.getenv("DIABETES_MODEL_NAME", getattr(settings, "DIABETES_MODEL_NAME", "DT")).upper()

    model_dir = Path(getattr(settings, "DIABETES_MODEL_DIR", Path(__file__).resolve().parent)).resolve()
    base_dir = Path(settings.BASE_DIR).resolve()

    model_filename = os.getenv(
        "DIABETES_MODEL_FILENAME",
        getattr(settings, "DIABETES_MODEL_FILENAME", None),
    )

    candidates: List[Path] = []

    # A) standard naming
    candidates += [
        model_dir / f"diabetes_{model_name}.joblib",
        model_dir / f"diabetes_{model_name}.gz",
        model_dir / f"diabetes_{model_name}.pkl",
        model_dir / f"diabetes_{model_name.lower()}.joblib",
        model_dir / f"diabetes_{model_name.lower()}.gz",
        model_dir / f"diabetes_{model_name.lower()}.pkl",
    ]

    # B) explicit filename
    if model_filename:
        candidates += [
            model_dir / model_filename,
            base_dir / "ml" / "artifacts" / model_filename,
            base_dir / "ml" / model_filename,
        ]

    # C) fallbacks
    candidates += [
        model_dir / "diabetes_model.joblib",
        model_dir / "diabetes_model.pkl",
        base_dir / "ml" / "artifacts" / "diabetes_model.joblib",
        base_dir / "ml" / "artifacts" / "diabetes_model.pkl",
    ]

    # de-dup preserving order
    seen: set[Path] = set()
    out: List[Path] = []
    for p in candidates:
        if p not in seen:
            out.append(p)
            seen.add(p)
    return out


def _resolve_model_path() -> Path:
    for p in _candidate_model_paths():
        if p.exists():
            return p
    raise FileNotFoundError(
        "Diabetes model not found. Checked:\n- " + "\n- ".join(str(p) for p in _candidate_model_paths())
    )


@lru_cache(maxsize=1)
def load_model() -> Any:
    path = _resolve_model_path()
    return joblib.load(path)


# -------------------------------------------------------------------
# Helpers
# -------------------------------------------------------------------
_LABEL_MAP = {
    "healthy": 0,
    "normal": 0,
    "non-diabetic": 0,
    "nondiabetic": 0,
    "no": 0,

    "prediabetic": 1,
    "pre-diabetic": 1,
    "pre": 1,

    "diabetic": 2,
    "diabetes": 2,
    "yes": 2,
}


def _class_to_int(cls: Any) -> int:
    if cls is None:
        raise ValueError("class is None")

    # numeric
    try:
        return int(cls)
    except Exception:
        pass

    s = str(cls).strip().lower()
    if s in _LABEL_MAP:
        return _LABEL_MAP[s]

    return int(float(s))


def _to_float(v: Any, default: float = 0.0) -> float:
    if v in (None, "", False):
        return default
    try:
        x = float(v)
        if not np.isfinite(x):
            return default
        return x
    except Exception:
        s = str(v).strip().lower()
        if s in {"yes", "y", "true", "on", "t", "1"}:
            return 1.0
        if s in {"no", "n", "false", "off", "f", "0"}:
            return 0.0
        return default


def _get_classes_attr(model: Any) -> Optional[List[Any]]:
    """
    Try to get classes_ from model or from wrapped estimators (Pipeline).
    """
    # direct
    c = getattr(model, "classes_", None)
    if c is not None:
        try:
            return list(c)
        except Exception:
            pass

    # sklearn Pipeline: last step often has classes_
    named_steps = getattr(model, "named_steps", None)
    if isinstance(named_steps, dict) and named_steps:
        # get last step by insertion order
        try:
            last_step = list(named_steps.values())[-1]
            c2 = getattr(last_step, "classes_", None)
            if c2 is not None:
                return list(c2)
        except Exception:
            pass

    return None


def _classes_list(model: Any) -> List[Any]:
    c = _get_classes_attr(model)
    return c if c is not None else []


def _binary_pos_neg_indices(model: Any) -> Tuple[int, int] | None:
    """
    For binary models (2 classes), return (pos_index, neg_index).

    Heuristic:
    - If classes represent {0,1} => 1 is positive
    - If class '2' appears (rare) => 2 is positive
    - Else => take max numeric as positive
    """
    classes = _classes_list(model)
    if len(classes) != 2:
        return None

    ints: List[Optional[int]] = []
    for c in classes:
        try:
            ints.append(_class_to_int(c))
        except Exception:
            ints.append(None)

    ints_only = [x for x in ints if x is not None]

    # prefer explicit 2
    if 2 in ints_only:
        pos = ints.index(2)  # type: ignore[arg-type]
        neg = 0 if pos == 1 else 1
        return (pos, neg)

    # {0,1} => 1 positive
    if set(ints_only) == {0, 1} and len(ints_only) == 2:
        pos = ints.index(1)  # type: ignore[arg-type]
        neg = ints.index(0)  # type: ignore[arg-type]
        return (pos, neg)

    # choose max as positive
    if len(ints_only) == 2:
        pos_int = max(ints_only)
        neg_int = min(ints_only)
        pos = ints.index(pos_int)  # type: ignore[arg-type]
        neg = ints.index(neg_int)  # type: ignore[arg-type]
        return (pos, neg)

    # fallback: assume index 1 is positive
    return (1, 0)


def _model_feature_order(model: Any) -> List[str]:
    """
    Prefer model.feature_names_in_ if present (or last estimator in pipeline), else DEFAULT_FEATURES.
    """
    # direct
    names = getattr(model, "feature_names_in_", None)
    if names is not None:
        try:
            return [str(x) for x in list(names)]
        except Exception:
            pass

    # pipeline last step
    named_steps = getattr(model, "named_steps", None)
    if isinstance(named_steps, dict) and named_steps:
        try:
            last_step = list(named_steps.values())[-1]
            names2 = getattr(last_step, "feature_names_in_", None)
            if names2 is not None:
                return [str(x) for x in list(names2)]
        except Exception:
            pass

    return list(DEFAULT_FEATURES)


def _build_X(features_dict: Dict[str, Any], feature_order: List[str]) -> Any:
    row = {f: _to_float(features_dict.get(f, 0.0)) for f in feature_order}

    if pd is not None:
        return pd.DataFrame([row], columns=feature_order).astype("float32")

    vec = np.asarray([row[f] for f in feature_order], dtype=np.float32).reshape(1, -1)
    return vec


def _predict_proba_dict(model: Any, X: Any) -> Dict[str, float]:
    """
    Always return {"0","1","2"} in SYSTEM space.

    - If model is binary => map NEG -> "0", POS -> "2", keep "1"=0.0
    - If model is multiclass and has 0/1/2 => map each directly
    """
    if not hasattr(model, "predict_proba"):
        raise RuntimeError("Model does not implement predict_proba().")

    proba_row = model.predict_proba(X)[0]
    out: Dict[str, float] = {"0": 0.0, "1": 0.0, "2": 0.0}

    classes = _classes_list(model)

    # If classes_ align with proba
    if classes and len(classes) == len(proba_row):
        # binary mapping to system 0/2
        if len(classes) == 2:
            idxs = _binary_pos_neg_indices(model)
            if idxs is not None:
                pos_i, neg_i = idxs
                out["0"] = float(proba_row[neg_i])
                out["2"] = float(proba_row[pos_i])
                out["1"] = 0.0
                return out

        # multiclass mapping (0/1/2)
        for cls, p in zip(classes, proba_row):
            try:
                k = str(_class_to_int(cls))
            except Exception:
                continue
            if k in out:
                out[k] = float(p)
        return out

    # Fallback: binary array length 2 => assume [neg, pos] and map pos->"2"
    try:
        if len(proba_row) == 2:
            out["0"] = float(proba_row[0])
            out["2"] = float(proba_row[1])
            out["1"] = 0.0
            return out
    except Exception:
        pass

    # Last fallback: assume order 0,1,2
    try:
        for i, p in enumerate(proba_row):
            if i in (0, 1, 2):
                out[str(i)] = float(p)
    except Exception:
        pass

    return out


def _predict_label(model: Any, X: Any, proba: Dict[str, float]) -> int:
    """
    Prefer model.predict; fallback to argmax over proba dict.

    Output label is always in SYSTEM space:
      - binary => 0 or 2
      - multiclass => 0/1/2
    """
    classes = _classes_list(model)

    if hasattr(model, "predict"):
        raw = model.predict(X)[0]

        # binary => map predicted raw class to system 0/2
        if classes and len(classes) == 2:
            idxs = _binary_pos_neg_indices(model)
            if idxs is not None:
                pos_i, _neg_i = idxs
                try:
                    raw_int = _class_to_int(raw)
                except Exception:
                    raw_int = None
                try:
                    pos_int = _class_to_int(classes[pos_i])
                except Exception:
                    pos_int = None
                if raw_int is not None and pos_int is not None:
                    return SYSTEM_DIABETIC if raw_int == pos_int else SYSTEM_HEALTHY
                # fallback via proba:
                return SYSTEM_DIABETIC if float(proba.get("2", 0.0)) >= 0.5 else SYSTEM_HEALTHY

        # multiclass => direct
        try:
            return int(_class_to_int(raw))
        except Exception:
            return SYSTEM_HEALTHY

    # fallback: choose best probability among system keys
    best_k = max(proba.keys(), key=lambda kk: float(proba.get(kk, 0.0)))
    return int(best_k)


def _risk_level(score: float, medium: float, high: float) -> str:
    if score >= high:
        return "High"
    if score >= medium:
        return "Medium"
    return "Low"


def _recommendation(level: str) -> str:
    if level == "High":
        return (
            "High risk (screening): consider confirmatory testing "
            "(HbA1c / fasting glucose) and clinical evaluation."
        )
    if level == "Medium":
        return (
            "Moderate risk (screening): consider confirmatory testing if symptoms "
            "or additional risk factors are present."
        )
    return (
        "Low risk (screening): continue routine follow-up. "
        "If symptoms appear, consider lab confirmation."
    )


def _label_text(predicted_class: int) -> str:
    if predicted_class == SYSTEM_DIABETIC:
        return "Diabetic"
    if predicted_class == SYSTEM_PREDIABETIC:
        return "Prediabetic"
    if predicted_class == SYSTEM_HEALTHY:
        return "Healthy"
    return f"Class {predicted_class}"


# -------------------------------------------------------------------
# Public API
# -------------------------------------------------------------------
def predict_diabetes(features_dict: Dict[str, Any]) -> DiabetesPrediction:
    """
    Predict diabetes status from a dict of features.

    Output:
      - proba always contains keys "0","1","2" in SYSTEM space
      - predicted_class:
          * multiclass: 0/1/2
          * binary: 0/2 (positive mapped to 2)
      - risk_score = P(diabetic) + 0.5*P(prediabetic)
        (binary => P(prediabetic)=0.0 so risk_score == P(diabetic))
    """
    model = load_model()
    feature_order = _model_feature_order(model)
    X = _build_X(features_dict, feature_order)

    proba = _predict_proba_dict(model, X)
    predicted_class = _predict_label(model, X, proba)

    diabetic_p = float(proba.get("2", 0.0))
    pre_p = float(proba.get("1", 0.0))
    risk_score = float(diabetic_p + 0.5 * pre_p)

    medium = float(getattr(settings, "DIABETES_RISK_MEDIUM", DEFAULT_RISK_MEDIUM))
    high = float(getattr(settings, "DIABETES_RISK_HIGH", DEFAULT_RISK_HIGH))
    risk = _risk_level(risk_score, medium, high)
    note = _recommendation(risk)

    return DiabetesPrediction(
        predicted_class=int(predicted_class),
        predicted_label=_label_text(int(predicted_class)),
        proba={k: float(v) for k, v in proba.items()},
        diabetic_probability=float(diabetic_p),
        risk_score=float(risk_score),
        risk_level=risk,
        recommendation=note,
        features_used=feature_order,
    )


def predict_proba_only(features_dict: Dict[str, Any]) -> Dict[str, float]:
    """
    Convenience helper if you only want probabilities.
    Always returns {"0","1","2"} in SYSTEM space.
    """
    return predict_diabetes(features_dict).proba
