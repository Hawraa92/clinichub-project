# patient/services.py
from __future__ import annotations

import json
import logging
import math
import os
from pathlib import Path
from threading import Lock
from typing import Any, Dict, Final, Iterable, List, Optional, Sequence, Tuple, Union

import joblib
import numpy as np
from django.conf import settings

from .models import DiabetesStatus, Patient

logger: Final = logging.getLogger(__name__)

# =============================================================================
#                               Safe parsing
# =============================================================================
_TRUE_SET: Final[set[str]] = {"1", "true", "yes", "y", "on", "t", "ok", "agree"}
_FALSE_SET: Final[set[str]] = {"0", "false", "no", "n", "off", "f", "none", "null"}


def _to_bool(v: Any, default: bool = False) -> bool:
    if v is None:
        return default
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        try:
            return bool(int(v))
        except Exception:
            return default
    s = str(v).strip().lower()
    if s in _TRUE_SET:
        return True
    if s in _FALSE_SET:
        return False
    return default


def _to01(v: Any, default: float = 0.0) -> float:
    return 1.0 if _to_bool(v, default=bool(default)) else 0.0


def _safe_float(v: Any, default: float = 0.0) -> float:
    """
    Best-effort float conversion:
    - None/"" -> default
    - yes/no-ish -> 1/0
    - supports comma decimal separator
    - rejects NaN/inf
    """
    if v is None:
        return default
    if v == "":
        return default

    # keep 0 as valid
    if v is False:
        return default

    try:
        x = float(v)
        if not math.isfinite(x):
            return default
        return x
    except Exception:
        s = str(v).strip().lower()
        if s in _TRUE_SET:
            return 1.0
        if s in _FALSE_SET:
            return 0.0
        try:
            x = float(s.replace(",", "."))
            if not math.isfinite(x):
                return default
            return x
        except Exception:
            return default


def _get_attr_first(obj: Any, names: Iterable[str], default: Any = None) -> Any:
    """
    Return the first non-empty value among candidate attribute names.
    NOTE: 0 is considered a valid value (so it will be returned).
    """
    for n in names:
        try:
            if hasattr(obj, n):
                val = getattr(obj, n)
                if val not in (None, ""):
                    return val
        except Exception:
            continue
    return default


# =============================================================================
#                          Model configuration / paths
# =============================================================================
MODEL_NAME: str = os.getenv(
    "DIABETES_MODEL_NAME",
    getattr(settings, "DIABETES_MODEL_NAME", "DT"),
).strip()

MODEL_NAME_UP: str = (MODEL_NAME or "DT").upper()
MODEL_NAME_LOW: str = (MODEL_NAME or "DT").lower()
MODEL_NAME_RAW: str = (MODEL_NAME or "DT")  # keep original casing

EXPLICIT_MODEL_PATH: Optional[str] = os.getenv(
    "DIABETES_MODEL_PATH",
    getattr(settings, "DIABETES_MODEL_PATH", None),
)

MODEL_FILENAME: Optional[str] = os.getenv(
    "DIABETES_MODEL_FILENAME",
    getattr(settings, "DIABETES_MODEL_FILENAME", None),
)

BASE_DIR: Final[Path] = Path(settings.BASE_DIR).resolve()

# Where we look by default:
# 1) settings.DIABETES_MODEL_DIR (if set)
# 2) patient/ml (legacy)
# 3) BASE_DIR/ml/artifacts (recommended layout)
# 4) BASE_DIR/ml
MODEL_DIR: Final[Path] = Path(
    getattr(settings, "DIABETES_MODEL_DIR", (Path(__file__).resolve().parent / "ml"))
).resolve()

ARTIFACTS_DIR: Final[Path] = (BASE_DIR / "ml" / "artifacts").resolve()
BASE_ML_DIR: Final[Path] = (BASE_DIR / "ml").resolve()

# عند التفعيل، سننسخ التنبؤ إلى diabetes_status أيضًا (غالبًا غير مُفضّل)
OVERWRITE_STATUS: bool = _to_bool(getattr(settings, "DIABETES_OVERWRITE_STATUS", False), default=False)

# Optional screening thresholds (NOT diagnosis)
RISK_MEDIUM: float = float(getattr(settings, "DIABETES_RISK_MEDIUM", 0.212))
RISK_HIGH: float = float(getattr(settings, "DIABETES_RISK_HIGH", 0.35))

# If True: include coverage/missing data info in quick_predict return dict
INCLUDE_COVERAGE: bool = _to_bool(getattr(settings, "DIABETES_INCLUDE_COVERAGE", True), default=True)


# =============================================================================
#                    Missing-data policy (screening guardrails)
# =============================================================================
class InsufficientDataError(RuntimeError):
    """Raised when prediction is withheld due to insufficient/low-quality input data."""


# أقل نسبة تغطية قبل ما نسمح بالتنبؤ
MIN_COVERAGE_RATIO: float = float(getattr(settings, "DIABETES_MIN_COVERAGE_RATIO", 0.55))

# الخصائص الضرورية (إذا ناقصة → نوقف التنبؤ)
REQUIRED_FEATURES: List[str] = list(getattr(settings, "DIABETES_REQUIRED_FEATURES", ["Age", "Sex", "BMI"]))

# إذا True: نوقف التنبؤ إذا insufficient (مفضل)
STRICT_INSUFFICIENT: bool = _to_bool(getattr(settings, "DIABETES_STRICT_INSUFFICIENT", True), default=True)


def _iter_dir_case_insensitive_matches(directory: Path, stem_prefix: str, target_fragment: str) -> List[Path]:
    """
    Case-insensitive scan helper for Linux case-sensitive filesystems.
    Looks for files that startwith stem_prefix and contain target_fragment (both case-insensitive).
    """
    out: List[Path] = []
    try:
        if not directory.exists() or not directory.is_dir():
            return out
        frag = target_fragment.lower()
        pref = stem_prefix.lower()
        for p in directory.iterdir():
            if not p.is_file():
                continue
            name = p.name.lower()
            if not (name.startswith(pref) and frag in name):
                continue
            if name.endswith((".joblib", ".pkl", ".gz")):
                out.append(p)
    except Exception:
        return out
    return out


def _candidate_model_paths() -> List[Path]:
    """
    Build candidates robustly:
    - EXPLICIT_MODEL_PATH wins
    - MODEL_FILENAME wins next (exact)
    - Try diabetes_{MODEL_NAME}.* with RAW/UP/LOW
    - Try fallbacks
    - Finally, do a case-insensitive scan in common dirs to catch mixed-case filenames
    """
    if EXPLICIT_MODEL_PATH:
        return [Path(EXPLICIT_MODEL_PATH).expanduser().resolve()]

    candidates: List[Path] = []

    # A) explicit filename if provided (exact)
    if MODEL_FILENAME:
        candidates += [
            MODEL_DIR / MODEL_FILENAME,
            ARTIFACTS_DIR / MODEL_FILENAME,
            BASE_ML_DIR / MODEL_FILENAME,
        ]

    # B) by name (RAW/UP/LOW) in MODEL_DIR
    for nm in (MODEL_NAME_RAW, MODEL_NAME_UP, MODEL_NAME_LOW):
        candidates += [
            MODEL_DIR / f"diabetes_{nm}.joblib",
            MODEL_DIR / f"diabetes_{nm}.pkl",
            MODEL_DIR / f"diabetes_{nm}.gz",
        ]

    # C) common fallback names
    candidates += [
        MODEL_DIR / "diabetes_model.joblib",
        MODEL_DIR / "diabetes_model.pkl",
        ARTIFACTS_DIR / "diabetes_model.joblib",
        ARTIFACTS_DIR / "diabetes_model.pkl",
        BASE_ML_DIR / "diabetes_model.joblib",
        BASE_ML_DIR / "diabetes_model.pkl",
    ]

    # D) case-insensitive scan to catch mixed-case model names (important on Linux/Render)
    scan_dirs = [MODEL_DIR, ARTIFACTS_DIR, BASE_ML_DIR]
    for d in scan_dirs:
        candidates += _iter_dir_case_insensitive_matches(d, "diabetes_", MODEL_NAME_RAW)

    # de-dup while preserving order
    seen: set[Path] = set()
    out: List[Path] = []
    for p in candidates:
        if p not in seen:
            out.append(p)
            seen.add(p)
    return out


def _resolve_model_path() -> Path:
    checked = _candidate_model_paths()
    for p in checked:
        try:
            if p.exists() and p.is_file():
                return p
        except Exception:
            continue

    hint = (
        "\n\nTips:\n"
        "- If your file name has mixed case (e.g. binary_RF...), either:\n"
        "  (1) set DIABETES_MODEL_FILENAME to the exact filename, OR\n"
        "  (2) rename the file to match diabetes_{DIABETES_MODEL_NAME}.joblib\n"
        "- Or set DIABETES_MODEL_PATH to an absolute path.\n"
    )
    raise RuntimeError(
        "No valid diabetes model file found.\nChecked:\n- " + "\n- ".join(str(p) for p in checked) + hint
    )


def _candidate_meta_paths(model_path: Path) -> List[Path]:
    """
    Prefer meta next to the model file:
      - <model_stem>_meta.json  (e.g. diabetes_xxx_meta.json)
      - <model_stem>.meta.json
    Then fallback to known names/dirs.
    """
    same_dir = model_path.parent
    stem = model_path.stem  # filename without extension

    cands: List[Path] = [
        same_dir / f"{stem}_meta.json",
        same_dir / f"{stem}.meta.json",
        same_dir / "diabetes_meta.json",
    ]

    # Also try name-based meta (RAW/UP/LOW) even if the model path was found via scan
    for nm in (MODEL_NAME_RAW, MODEL_NAME_UP, MODEL_NAME_LOW):
        cands += [
            same_dir / f"diabetes_{nm}_meta.json",
            MODEL_DIR / f"diabetes_{nm}_meta.json",
            ARTIFACTS_DIR / f"diabetes_{nm}_meta.json",
        ]

    cands += [
        MODEL_DIR / "diabetes_meta.json",
        ARTIFACTS_DIR / "diabetes_meta.json",
        BASE_ML_DIR / "diabetes_meta.json",
    ]

    seen: set[Path] = set()
    out: List[Path] = []
    for p in cands:
        if p not in seen:
            out.append(p)
            seen.add(p)
    return out


# =============================================================================
#                         Lazy model/meta loading (thread-safe)
# =============================================================================
_model: Optional[Any] = None
_meta: Dict[str, Any] = {}
_feature_order: Optional[List[str]] = None
_model_path: Optional[Path] = None
_load_lock: Final[Lock] = Lock()


def reload_model() -> None:
    """
    Force reload (useful if you changed env vars / replaced model file without restarting).
    """
    global _model, _meta, _feature_order, _model_path
    with _load_lock:
        _model = None
        _meta = {}
        _feature_order = None
        _model_path = None
    logger.info("[%s] Diabetes model cache cleared. Will reload on next prediction.", MODEL_NAME_UP)


def _load_model_file(path: Path) -> Any:
    logger.info("[%s] Loading ML model: %s", MODEL_NAME_UP, path)
    model = joblib.load(path)

    # basic sanity checks
    if not hasattr(model, "predict"):
        raise RuntimeError(f"Loaded object has no predict(): {type(model)!r}")
    if not hasattr(model, "predict_proba"):
        raise RuntimeError(f"Loaded object has no predict_proba(): {type(model)!r}")

    return model


def _init_model_and_meta() -> None:
    """
    Initialize model + meta once.
    """
    global _model, _meta, _feature_order, _model_path

    path = _resolve_model_path()
    model = _load_model_file(path)

    meta: Dict[str, Any] = {}
    for mp in _candidate_meta_paths(path):
        try:
            if mp.exists() and mp.is_file():
                data = json.loads(mp.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    meta = data
                    logger.info("[%s] Loaded diabetes meta: %s", MODEL_NAME_UP, mp.name)
                    break
        except Exception as exc:
            logger.warning("[%s] Meta load failed (%s): %s", MODEL_NAME_UP, getattr(mp, "name", "?"), exc)

    if not meta:
        logger.info("[%s] Meta file not found (will infer feature order).", MODEL_NAME_UP)

    _model = model
    _meta = meta
    _feature_order = None
    _model_path = path


def _get_model() -> Any:
    global _model
    if _model is None:
        with _load_lock:
            if _model is None:
                _init_model_and_meta()
    return _model


# =============================================================================
#                      Feature order + mapping (BRFSS style)
# =============================================================================
DEFAULT_MODEL_FEATURES: List[str] = [
    "HighBP",
    "HighChol",
    "CholCheck",
    "BMI",
    "Smoker",
    "Stroke",
    "HeartDiseaseorAttack",
    "PhysActivity",
    "Fruits",
    "Veggies",
    "HvyAlcoholConsump",
    "AnyHealthcare",
    "NoDocbcCost",
    "GenHlth",
    "MentHlth",
    "PhysHlth",
    "DiffWalk",
    "Sex",
    "Age",
    "Education",
    "Income",
]


def _sex_from_patient(p: Patient) -> float:
    v = getattr(p, "sex", None)
    if v is None:
        return 0.0
    if isinstance(v, (int, float)):
        return 1.0 if int(v) == 1 else 0.0

    s = str(v).strip().lower()
    if s in {"m", "male", "man", "ذكر", "1"}:
        return 1.0
    if s in {"f", "female", "woman", "انثى", "أنثى", "0", "2"}:
        return 0.0
    return 0.0


def _age_to_brfss_group(age_years: int) -> int:
    if age_years < 18:
        return 0
    if age_years <= 24:
        return 1
    if age_years <= 29:
        return 2
    if age_years <= 34:
        return 3
    if age_years <= 39:
        return 4
    if age_years <= 44:
        return 5
    if age_years <= 49:
        return 6
    if age_years <= 54:
        return 7
    if age_years <= 59:
        return 8
    if age_years <= 64:
        return 9
    if age_years <= 69:
        return 10
    if age_years <= 74:
        return 11
    if age_years <= 79:
        return 12
    return 13


def _age_years_from_patient(p: Patient) -> int:
    # 1) prefer display_age property if exists
    try:
        disp = getattr(p, "display_age", None)
        if disp not in (None, "", 0, "0"):
            return int(float(disp))
    except Exception:
        pass

    # 2) explicit numeric fields
    for key in ("age_years", "age"):
        v = getattr(p, key, None)
        if v not in (None, "", 0, "0"):
            try:
                return int(float(v))
            except Exception:
                continue

    # 3) compute from DOB
    dob = getattr(p, "date_of_birth", None)
    if dob:
        try:
            from django.utils import timezone

            today = timezone.localdate()
            yrs = today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))
            return int(yrs)
        except Exception:
            return 0

    return 0


def _age_group_from_patient(p: Patient) -> float:
    ag = getattr(p, "age_group", None)
    if ag not in (None, "", "0"):
        try:
            return float(ag)
        except Exception:
            pass

    yrs = _age_years_from_patient(p)
    if yrs <= 0:
        return 0.0
    return float(_age_to_brfss_group(int(yrs)))


def _compute_bmi_from_patient(p: Patient) -> Optional[float]:
    """
    Compute BMI if not stored.
    Accepts:
      - weight_kg / weight
      - height_cm / height (cm) OR height_m (meters)
    Returns None if insufficient/invalid.
    """
    # Try explicit BMI field first
    bmi_val = _get_attr_first(p, ["bmi", "BMI"], None)
    if bmi_val not in (None, ""):
        bmi = _safe_float(bmi_val, 0.0)
        return bmi if bmi > 0 else None

    w = _get_attr_first(p, ["weight_kg", "weight", "body_weight"], None)
    h_cm = _get_attr_first(p, ["height_cm", "height", "body_height_cm"], None)
    h_m = _get_attr_first(p, ["height_m", "body_height_m"], None)

    weight = _safe_float(w, 0.0)
    if weight <= 0:
        return None

    if h_m not in (None, ""):
        hm = _safe_float(h_m, 0.0)
        if hm > 0.5 and hm < 3.0:
            bmi = weight / (hm * hm)
            return float(bmi) if math.isfinite(bmi) and bmi > 0 else None

    if h_cm not in (None, ""):
        hc = _safe_float(h_cm, 0.0)
        if hc > 30 and hc < 300:
            hm = hc / 100.0
            bmi = weight / (hm * hm)
            return float(bmi) if math.isfinite(bmi) and bmi > 0 else None

    return None


# For “coverage” detection (what source fields we look at per feature)
FEATURE_SOURCES: Dict[str, List[str]] = {
    "HighBP": ["high_bp", "high_blood_pressure"],
    "HighChol": ["high_chol", "high_cholesterol"],
    "CholCheck": ["chol_check", "cholesterol_checked"],
    "BMI": ["bmi", "BMI", "weight_kg", "weight", "height_cm", "height", "height_m"],
    "Smoker": ["smoker", "smoking", "smoking_history"],
    "Stroke": ["stroke"],
    "HeartDiseaseorAttack": ["heart_disease_or_attack", "heart_disease", "heart_attack"],
    "PhysActivity": ["phys_activity", "physical_activity"],
    "Fruits": ["fruits", "eats_fruits_regularly"],
    "Veggies": ["veggies", "eats_veggies_regularly"],
    "HvyAlcoholConsump": ["hvy_alcohol_consump", "heavy_alcohol_consumption"],
    "AnyHealthcare": ["any_healthcare", "healthcare_coverage"],
    "NoDocbcCost": ["no_doc_bc_cost", "could_not_see_doctor_due_to_cost"],
    "GenHlth": ["gen_hlth", "general_health"],
    "MentHlth": ["ment_hlth", "mental_health_days"],
    "PhysHlth": ["phys_hlth", "physical_health_days"],
    "DiffWalk": ["diff_walk", "difficulty_walking"],
    "Sex": ["sex"],
    "Age": ["age_group", "age_years", "age", "display_age", "date_of_birth"],
    "Education": ["education", "education_level"],
    "Income": ["income", "income_level"],
    # optional if model requests
    "HbA1c": ["hbA1c", "hba1c", "HbA1c"],
    "Glucose": ["glucose", "blood_glucose"],
    "AgeYears": ["age_years", "age", "display_age", "date_of_birth"],
}


def _feature_present(p: Patient, feat: str) -> bool:
    """
    Best-effort: returns True if we likely have data for a feature.
    For BMI: accepts either BMI OR both weight+height.
    """
    keys = FEATURE_SOURCES.get(feat, [])
    if not keys:
        return False

    # BMI special
    if feat == "BMI":
        bmi = _compute_bmi_from_patient(p)
        if bmi is not None and bmi > 0:
            return True
        # fallback: any stored bmi field?
        for k in ("bmi", "BMI"):
            try:
                if hasattr(p, k) and getattr(p, k) not in (None, ""):
                    return True
            except Exception:
                pass
        return False

    # Sex special: treat unknown/unrecognized as missing
    if feat == "Sex":
        v = getattr(p, "sex", None)
        if v in (None, ""):
            return False
        if isinstance(v, (int, float)):
            try:
                return int(v) in (0, 1, 2)
            except Exception:
                return False
        s = str(v).strip().lower()
        return s in {"m", "male", "man", "ذكر", "1", "f", "female", "woman", "انثى", "أنثى", "0", "2"}

    # Age special: accept any of its sources
    if feat in {"Age", "AgeYears"}:
        yrs = _age_years_from_patient(p)
        if yrs > 0:
            return True
        ag = getattr(p, "age_group", None)
        return ag not in (None, "", "0")

    # Generic
    for k in keys:
        try:
            if hasattr(p, k):
                v = getattr(p, k)
                if v not in (None, ""):
                    return True
        except Exception:
            continue
    return False


FEATURE_MAP: Dict[str, Any] = {
    # Core BRFSS
    "HighBP": lambda p: _to01(_get_attr_first(p, ["high_bp", "high_blood_pressure"], 0)),
    "HighChol": lambda p: _to01(_get_attr_first(p, ["high_chol", "high_cholesterol"], 0)),
    "CholCheck": lambda p: _to01(_get_attr_first(p, ["chol_check", "cholesterol_checked"], 0)),
    "BMI": lambda p: _safe_float(_compute_bmi_from_patient(p), 0.0),
    "Smoker": lambda p: _to01(_get_attr_first(p, ["smoker", "smoking", "smoking_history"], 0)),
    "Stroke": lambda p: _to01(_get_attr_first(p, ["stroke"], 0)),
    "HeartDiseaseorAttack": lambda p: _to01(
        _get_attr_first(p, ["heart_disease_or_attack", "heart_disease", "heart_attack"], 0)
    ),
    "PhysActivity": lambda p: _to01(_get_attr_first(p, ["phys_activity", "physical_activity"], 0)),
    "Fruits": lambda p: _to01(_get_attr_first(p, ["fruits", "eats_fruits_regularly"], 0)),
    "Veggies": lambda p: _to01(_get_attr_first(p, ["veggies", "eats_veggies_regularly"], 0)),
    "HvyAlcoholConsump": lambda p: _to01(_get_attr_first(p, ["hvy_alcohol_consump", "heavy_alcohol_consumption"], 0)),
    "AnyHealthcare": lambda p: _to01(_get_attr_first(p, ["any_healthcare", "healthcare_coverage"], 0)),
    "NoDocbcCost": lambda p: _to01(_get_attr_first(p, ["no_doc_bc_cost", "could_not_see_doctor_due_to_cost"], 0)),
    "GenHlth": lambda p: _safe_float(_get_attr_first(p, ["gen_hlth", "general_health"], 0), 0.0),
    "MentHlth": lambda p: _safe_float(_get_attr_first(p, ["ment_hlth", "mental_health_days"], 0), 0.0),
    "PhysHlth": lambda p: _safe_float(_get_attr_first(p, ["phys_hlth", "physical_health_days"], 0), 0.0),
    "DiffWalk": lambda p: _to01(_get_attr_first(p, ["diff_walk", "difficulty_walking"], 0)),
    "Sex": _sex_from_patient,
    "Age": _age_group_from_patient,
    "Education": lambda p: _safe_float(_get_attr_first(p, ["education", "education_level"], 0), 0.0),
    "Income": lambda p: _safe_float(_get_attr_first(p, ["income", "income_level"], 0), 0.0),
    # Optional (only if model/meta requests)
    "HbA1c": lambda p: _safe_float(_get_attr_first(p, ["hbA1c", "hba1c", "HbA1c"], 0.0), 0.0),
    "Glucose": lambda p: _safe_float(_get_attr_first(p, ["glucose", "blood_glucose"], 0.0), 0.0),
    "AgeYears": lambda p: float(max(_age_years_from_patient(p), 0)),
}


def _infer_feature_order_from_model(model: Any) -> Optional[List[str]]:
    # scikit-learn estimators often have feature_names_in_
    try:
        fn = getattr(model, "feature_names_in_", None)
        if fn is not None:
            return [str(x) for x in list(fn)]
    except Exception:
        pass

    # pipelines: look for final estimator
    try:
        steps = getattr(model, "steps", None)
        if steps:
            last = steps[-1][1]
            fn = getattr(last, "feature_names_in_", None)
            if fn is not None:
                return [str(x) for x in list(fn)]
    except Exception:
        pass

    return None


def _ensure_feature_order() -> List[str]:
    """
    Determine final feature order:
    1) meta["features"] or meta["feature_order"] if valid
    2) model.feature_names_in_ if present
    3) DEFAULT_MODEL_FEATURES
    """
    global _feature_order
    if _feature_order is not None:
        return _feature_order

    model = _get_model()

    feats: Any = None
    if isinstance(_meta, dict):
        feats = _meta.get("features") or _meta.get("feature_order")

    if isinstance(feats, list) and all(isinstance(x, str) for x in feats):
        order = [x.strip() for x in feats if x and x.strip()]
    else:
        inferred = _infer_feature_order_from_model(model)
        order = inferred if inferred else list(DEFAULT_MODEL_FEATURES)

    unknown = [f for f in order if f not in FEATURE_MAP]
    if unknown:
        logger.warning("[%s] Unknown features with no mapping (will use 0.0): %s", MODEL_NAME_UP, unknown)

    _feature_order = order
    return _feature_order


def patient_to_feature_dict(p: Patient) -> Dict[str, float]:
    feats = _ensure_feature_order()
    out: Dict[str, float] = {}
    for feat in feats:
        fn = FEATURE_MAP.get(feat)
        raw: Any = None
        try:
            if callable(fn):
                raw = fn(p)
            elif isinstance(fn, str):
                raw = getattr(p, fn, None)
        except Exception:
            raw = None
        out[feat] = _safe_float(raw, 0.0)
    return out


def _patient_to_vector(p: Patient) -> np.ndarray:
    feats = _ensure_feature_order()
    vals: List[float] = []
    for feat in feats:
        fn = FEATURE_MAP.get(feat)
        raw: Any = None
        try:
            if callable(fn):
                raw = fn(p)
            elif isinstance(fn, str):
                raw = getattr(p, fn, None)
        except Exception:
            raw = None
        vals.append(_safe_float(raw, 0.0))
    return np.asarray(vals, dtype=np.float32).reshape(1, -1)


def _patient_to_model_input(p: Patient, feats: List[str]) -> Any:
    """
    Prefer returning a pandas.DataFrame with feature names (removes sklearn warning),
    but fallback to numpy array if pandas isn't available.
    """
    X = _patient_to_vector(p)
    try:
        import pandas as pd  # type: ignore

        return pd.DataFrame(X, columns=feats)
    except Exception:
        return X


def _coverage_payload(patient: Patient, feats: List[str]) -> Dict[str, Any]:
    missing = [f for f in feats if not _feature_present(patient, f)]
    present = max(len(feats) - len(missing), 0)
    ratio = (present / len(feats)) if feats else 0.0
    missing_required = [f for f in REQUIRED_FEATURES if f in feats and f in missing]

    return {
        "present": int(present),
        "total": int(len(feats)),
        "ratio": round(float(ratio), 4),
        "missing": missing,
        "missing_required": missing_required,
        "policy": {
            "min_coverage_ratio": float(MIN_COVERAGE_RATIO),
            "required_features": list(REQUIRED_FEATURES),
            "strict": bool(STRICT_INSUFFICIENT),
        },
        "note": (
            "This is screening support only (NOT diagnosis). "
            "If key data are missing (Age/Sex/BMI) or coverage is low, prediction is withheld."
        ),
    }


# =============================================================================
#                         Prediction mapping (labels/classes)
# =============================================================================
# NOTE:
# System codes are fixed as:
#   0 = Normal, 1 = Prediabetes, 2 = Diabetes
# But if the ML model is binary, we map:
#   negative -> 0
#   positive -> 2
# and keep 1 unused.
_LABEL_MAP: Final[Dict[str, int]] = {
    "healthy": 0,
    "normal": 0,
    "no": 0,
    "nondiabetic": 0,
    "non-diabetic": 0,
    "non diabetic": 0,
    "prediabetic": 1,
    "pre-diabetic": 1,
    "pre diabetic": 1,
    "pre": 1,
    "diabetic": 2,
    "diabetes": 2,
    "yes": 2,
}


def _raw_to_int_maybe(cls: Any) -> Optional[int]:
    try:
        return int(cls)
    except Exception:
        pass
    s = str(cls).strip().lower()
    if s in _LABEL_MAP:
        return _LABEL_MAP[s]
    try:
        return int(float(s))
    except Exception:
        return None


def _classes_list(model: Any) -> List[Any]:
    """
    Safe classes_ extraction (NO 'or []' because numpy arrays break truthiness).
    """
    try:
        classes_obj = getattr(model, "classes_", None)
        if classes_obj is None:
            return []
        return list(classes_obj)
    except Exception:
        return []


def _is_binary_model(model: Any) -> bool:
    try:
        return len(_classes_list(model)) == 2
    except Exception:
        return False


def _class_equal(a: Any, b: Any) -> bool:
    ai = _raw_to_int_maybe(a)
    bi = _raw_to_int_maybe(b)
    if ai is not None and bi is not None:
        return ai == bi
    return str(a).strip().lower() == str(b).strip().lower()


def _binary_pos_neg_indices(model: Any) -> Tuple[int, int]:
    """
    Return (pos_index, neg_index) for binary model classes_.

    Heuristic:
    - prefer explicit diabetes code "2"
    - else prefer "1" as positive if {0,1}
    - else highest numeric label is positive
    - fallback pos=1, neg=0
    """
    classes = _classes_list(model)
    if len(classes) != 2:
        return (1, 0)

    cls_ints: List[Optional[int]] = [_raw_to_int_maybe(c) for c in classes]

    # prefer explicit 2
    ints_only = [x for x in cls_ints if x is not None]
    if 2 in ints_only:
        pos = cls_ints.index(2)  # type: ignore[arg-type]
        neg = 0 if pos == 1 else 1
        return (pos, neg)

    # {0,1} => 1 is positive
    if set(ints_only) == {0, 1}:
        pos = cls_ints.index(1)  # type: ignore[arg-type]
        neg = cls_ints.index(0)  # type: ignore[arg-type]
        return (pos, neg)

    # choose max as positive if both numeric
    ints = [(i, x) for i, x in enumerate(cls_ints) if x is not None]
    if len(ints) == 2:
        pos = max(ints, key=lambda t: t[1])[0]
        neg = min(ints, key=lambda t: t[1])[0]
        return (pos, neg)

    return (1, 0)


def _normalize_label(raw_label: Any, model: Any) -> int:
    """
    Convert raw predicted class into our DiabetesStatus codes:
      0=Normal, 1=Prediabetes, 2=Diabetes

    For binary models:
      negative -> 0
      positive -> 2
    """
    if _is_binary_model(model):
        pos_i, _neg_i = _binary_pos_neg_indices(model)
        classes = _classes_list(model)
        pos_cls = classes[pos_i] if len(classes) == 2 else 1
        return 2 if _class_equal(raw_label, pos_cls) else 0

    v = _raw_to_int_maybe(raw_label)
    if v is None:
        raise ValueError(f"Unsupported class label: {raw_label!r}")

    if v in (0, 1, 2):
        return v

    if v < 0:
        return 0
    if v > 2:
        return 2
    return v


def _proba_to_dict(model: Any, proba_row: Any) -> Dict[str, float]:
    """
    Normalize predict_proba output to {"0":p0,"1":p1,"2":p2}.

    For binary models:
      - negative mapped to "0"
      - positive mapped to "2"
      - "1" stays 0.0
    """
    out: Dict[str, float] = {"0": 0.0, "1": 0.0, "2": 0.0}

    classes = _classes_list(model)

    try:
        proba_list = [float(x) for x in list(proba_row)]
    except Exception:
        proba_list = []

    # aligned case
    if classes and proba_list and len(classes) == len(proba_list):
        if len(classes) == 2:
            pos_i, neg_i = _binary_pos_neg_indices(model)
            out["0"] = float(proba_list[neg_i])
            out["2"] = float(proba_list[pos_i])
            out["1"] = 0.0
            return out

        # multiclass alignment by class labels
        for cls, p in zip(classes, proba_list):
            ci = _raw_to_int_maybe(cls)
            if ci is None:
                continue
            if ci in (0, 1, 2):
                out[str(ci)] = float(p)
        return out

    # fallback: if proba looks binary (len==2), assume [neg,pos] => map to 0/2
    if len(proba_list) == 2:
        out["0"] = float(proba_list[0])
        out["2"] = float(proba_list[1])
        out["1"] = 0.0
        return out

    # last fallback: assume order 0,1,2
    try:
        for i, p in enumerate(proba_list):
            if i in (0, 1, 2):
                out[str(i)] = float(p)
    except Exception:
        pass

    # clamp and finiteness
    for k in ("0", "1", "2"):
        try:
            v = float(out.get(k, 0.0))
            out[k] = v if math.isfinite(v) else 0.0
        except Exception:
            out[k] = 0.0

    return out


def _risk_band_from_proba(proba: Dict[str, float]) -> str:
    """
    Simple screening band based on P(diabetes) i.e. proba["2"] for our mapping.
    """
    try:
        p_diabetes = float(proba.get("2", 0.0))
    except Exception:
        p_diabetes = 0.0

    if p_diabetes >= RISK_HIGH:
        return "high"
    if p_diabetes >= RISK_MEDIUM:
        return "medium"
    return "low"


# =============================================================================
#                              DB field picking
# =============================================================================
def _has_field(model_cls: type, field_name: str) -> bool:
    try:
        model_cls._meta.get_field(field_name)
        return True
    except Exception:
        return False


def _field_is_json(model_cls: type, field_name: str) -> bool:
    """
    Works across Django versions without importing JSONField directly.
    """
    try:
        f = model_cls._meta.get_field(field_name)
        return getattr(f, "get_internal_type", lambda: "")() == "JSONField"
    except Exception:
        return False


def _pick_existing_field(model_cls: type, candidates: Sequence[str]) -> Optional[str]:
    for name in candidates:
        if _has_field(model_cls, name):
            return name
    return None


# =============================================================================
#                              Public APIs
# =============================================================================
def get_model_info() -> Dict[str, Any]:
    """
    Small helper for debugging in shell/admin.
    """
    model = _get_model()
    classes = [str(x) for x in _classes_list(model)]

    return {
        "model_name": MODEL_NAME_RAW,
        "model_path": str(_model_path) if _model_path else "",
        "model_dir": str(MODEL_DIR),
        "features": _ensure_feature_order(),
        "has_meta": bool(_meta),
        "classes": classes,
        "is_binary": _is_binary_model(model),
        "risk_medium": RISK_MEDIUM,
        "risk_high": RISK_HIGH,
        "missing_policy": {
            "min_coverage_ratio": MIN_COVERAGE_RATIO,
            "required_features": REQUIRED_FEATURES,
            "strict": STRICT_INSUFFICIENT,
        },
    }


def quick_predict(patient: Patient) -> Dict[str, Any]:
    """
    Predict without writing to DB.

    Returns:
      {
        "label": int | None,
        "proba": {"0":float,"1":float,"2":float},
        "risk_band": "low|medium|high|unknown",
        "features": [...],
        "model_path": "...",
        "insufficient_data": bool,
        "reasons": [...],
        "coverage": {...}   # if enabled
      }
    """
    model = _get_model()
    feats = _ensure_feature_order()

    coverage = _coverage_payload(patient, feats) if INCLUDE_COVERAGE else None
    missing_required = (coverage or {}).get("missing_required", []) if coverage else []
    ratio = float((coverage or {}).get("ratio", 0.0)) if coverage else 1.0

    insufficient = False
    reasons: List[str] = []

    if missing_required:
        insufficient = True
        reasons.append(f"missing_required={missing_required}")

    if feats and ratio < MIN_COVERAGE_RATIO:
        insufficient = True
        reasons.append(f"coverage_ratio<{MIN_COVERAGE_RATIO}")

    if STRICT_INSUFFICIENT and insufficient:
        out: Dict[str, Any] = {
            "label": None,
            "proba": {"0": 0.0, "1": 0.0, "2": 0.0},
            "risk_band": "unknown",
            "features": feats,
            "model_path": str(_model_path) if _model_path else "",
            "insufficient_data": True,
            "reasons": reasons,
        }
        if INCLUDE_COVERAGE:
            out["coverage"] = coverage
        return out

    # Build model input (prefer DataFrame for proper feature names)
    X = _patient_to_model_input(patient, feats)

    # Validate expected feature count if model exposes it
    try:
        n_expected = getattr(model, "n_features_in_", None)
        n_got = int(getattr(X, "shape")[1])  # DataFrame/ndarray
        if isinstance(n_expected, (int, np.integer)) and int(n_expected) != int(n_got):
            raise RuntimeError(
                f"Feature shape mismatch: model expects {int(n_expected)} features, "
                f"but got {int(n_got)}. Feature order used: {feats}"
            )
    except RuntimeError:
        raise
    except Exception:
        pass

    # Predict label
    try:
        raw_label = model.predict(X)[0]
        label = _normalize_label(raw_label, model)
    except Exception as exc:
        raise RuntimeError(f"Model.predict error: {exc}") from exc

    # Predict proba
    try:
        proba_arr = model.predict_proba(X)[0]  # type: ignore[attr-defined]
    except AttributeError as exc:
        raise RuntimeError("Model lacks predict_proba") from exc
    except Exception as exc:
        raise RuntimeError(f"Model.predict_proba error: {exc}") from exc

    proba = _proba_to_dict(model, proba_arr)
    band = _risk_band_from_proba(proba)

    out: Dict[str, Any] = {
        "label": int(label),
        "proba": proba,
        "risk_band": band,
        "features": feats,
        "model_path": str(_model_path) if _model_path else "",
        "insufficient_data": False,
        "reasons": [],
    }

    if INCLUDE_COVERAGE:
        out["coverage"] = coverage

    return out


def predict_and_save(patient: Patient, *, return_payload: bool = False) -> Union[int, Dict[str, Any]]:
    """
    Saves prediction into patient fields WITHOUT triggering recursive signals
    (uses QuerySet.update).

    Default return: label int (backward compatible).
    If return_payload=True: returns dict payload like quick_predict + saved fields list.
    """
    if not getattr(patient, "pk", None):
        raise RuntimeError("Patient must be saved before prediction (missing pk).")

    result = quick_predict(patient)

    # إذا البيانات غير كافية: لا نحفظ ولا نرجع رقم مضلل
    if result.get("insufficient_data"):
        raise InsufficientDataError(f"Prediction withheld (insufficient data): {result.get('reasons')}")

    raw_label = result.get("label", None)
    if raw_label is None:
        raise InsufficientDataError("Prediction withheld: label is None due to insufficient data.")

    label: int = int(raw_label)

    proba_raw = dict(result.get("proba") or {})
    proba: Dict[str, float] = {k: round(float(v), 6) for k, v in proba_raw.items()}

    pred_field = _pick_existing_field(Patient, ["diabetes_prediction", "prediction", "ai_prediction"])
    proba_field = _pick_existing_field(
        Patient,
        ["prediction_proba", "diabetes_prediction_proba", "diabetes_proba", "proba"],
    )

    update: Dict[str, Any] = {}
    saved_fields: List[str] = []

    if pred_field:
        update[pred_field] = label
        saved_fields.append(pred_field)

    if proba_field:
        if _field_is_json(Patient, proba_field):
            update[proba_field] = proba
        else:
            update[proba_field] = json.dumps(proba, ensure_ascii=False)
        saved_fields.append(proba_field)

    if OVERWRITE_STATUS and _has_field(Patient, "diabetes_status"):
        update["diabetes_status"] = label
        saved_fields.append("diabetes_status")

    if not update:
        raise RuntimeError(
            "No suitable Patient fields found to save prediction. "
            "Expected at least one of: diabetes_prediction / prediction_proba (or fallbacks)."
        )

    # Atomic DB update (no signals)
    Patient.objects.filter(pk=patient.pk).update(**update)

    # Keep instance in sync (nice-to-have)
    for k, v in update.items():
        try:
            setattr(patient, k, v)
        except Exception:
            pass

    try:
        lbl = DiabetesStatus(label).label
    except Exception:
        lbl = str(label)

    logger.debug(
        "[%s] Patient %s → %s (saved=%s, model=%s)",
        MODEL_NAME_UP,
        patient.pk,
        lbl,
        saved_fields,
        str(_model_path) if _model_path else "?",
    )

    if return_payload:
        payload = dict(result)
        payload["saved_fields"] = saved_fields
        return payload

    return label


def bulk_predict_and_save(qs: Sequence[Patient]) -> Tuple[int, int]:
    """
    Bulk helper (iterative) — keeps behavior predictable and logs errors.
    Returns (ok, err).
    """
    _get_model()  # ensure model is loaded once
    ok = 0
    err = 0

    for p in qs:
        try:
            if not getattr(p, "pk", None):
                continue
            predict_and_save(p)
            ok += 1
        except InsufficientDataError as exc:  # insufficient data is not a "system error"
            logger.info("[%s] Withheld for Patient %s: %s", MODEL_NAME_UP, getattr(p, "pk", "?"), exc)
            err += 1
        except Exception as exc:  # pragma: no cover
            logger.warning("[%s] Predict failed for Patient %s: %s", MODEL_NAME_UP, getattr(p, "pk", "?"), exc)
            err += 1

    return ok, err
