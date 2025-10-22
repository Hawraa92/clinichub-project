"""
patient/services.py
Refactor 06-Aug-2025 — تحميل كسول للنموذج، خريطة ميزات دقيقة Patient→Model،
وسلوك آمن لا يُعدّل diabetes_status يدويًا إلا إذا فُعِّل صراحة.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any, Final, List, Optional, Sequence, Tuple, Dict

import joblib
import numpy as np
from django.conf import settings

from .models import Patient, DiabetesStatus

logger: Final = logging.getLogger(__name__)

# ------------------------------------------------------------------ #
#                        اختيار النموذج والمسارات                     #
# ------------------------------------------------------------------ #
MODEL_NAME: str = os.getenv(
    "DIABETES_MODEL_NAME",
    getattr(settings, "DIABETES_MODEL_NAME", "DT"),
).upper()

MODEL_DIR: Final[Path] = Path(__file__).resolve().parent / "ml"
_MODEL_LZMA: Final[Path] = MODEL_DIR / f"diabetes_{MODEL_NAME}.joblib"
_MODEL_GZ:   Final[Path] = MODEL_DIR / f"diabetes_{MODEL_NAME}.gz"
_MODEL_PKL:  Final[Path] = MODEL_DIR / f"diabetes_{MODEL_NAME}.pkl"
_META_PATH:  Final[Path] = MODEL_DIR / f"diabetes_{MODEL_NAME}_meta.json"

# عند التفعيل، سننسخ التنبؤ إلى diabetes_status أيضًا (غير مُفضّل غالبًا)
OVERWRITE_STATUS: bool = bool(getattr(settings, "DIABETES_OVERWRITE_STATUS", False))

# ------------------------------------------------------------------ #
#                     التحميل الكسول للنموذج والميتا                  #
# ------------------------------------------------------------------ #
_model: Optional[Any] = None
_meta: Dict[str, Any] = {}
_feature_order: Optional[List[str]] = None  # أسماء ميزات النموذج (كما حُفِظت بالـmeta)

def _load_model_file(path: Path) -> Any:
    logger.info("Loading ML model: %s", path.name)
    return joblib.load(path)

def _init_model() -> Any:
    """جرّب تحميل عدّة امتدادات بالترتيب."""
    for f in (_MODEL_LZMA, _MODEL_GZ, _MODEL_PKL):
        if f.exists():
            try:
                return _load_model_file(f)
            except Exception as exc:  # pragma: no cover
                logger.warning("Failed to load %s: %s", f.name, exc)
    raise RuntimeError(f"No valid model file found for MODEL_NAME={MODEL_NAME}")

def _init_meta() -> Dict[str, Any]:
    if _META_PATH.exists():
        try:
            data = json.loads(_META_PATH.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                raise ValueError("Meta is not a JSON object")
            return data
        except Exception as exc:  # pragma: no cover
            logger.warning("Meta load failed (%s): %s", _META_PATH.name, exc)
    else:
        logger.warning("Meta file not found: %s", _META_PATH.name)
    return {}

def _get_model() -> Any:
    global _model, _meta, _feature_order
    if _model is None:
        _model = _init_model()
        _meta = _init_meta()
        _feature_order = None  # سنُولّدها عند الطلب
    return _model

# ------------------------------------------------------------------ #
#                  ترتيب الميزات + خريطة الاسماء                    #
# ------------------------------------------------------------------ #
# الميزات الافتراضية (مطابقة لسكربت التدريب) إذا لم تُوجَد في meta
DEFAULT_MODEL_FEATURES: List[str] = [
    "HighBP", "HighChol", "CholCheck", "BMI", "Smoker", "Stroke",
    "HeartDiseaseorAttack", "PhysActivity", "Fruits", "Veggies",
    "HvyAlcoholConsump", "AnyHealthcare", "NoDocbcCost", "GenHlth",
    "MentHlth", "PhysHlth", "DiffWalk", "Sex", "Age", "Education", "Income",
]

# خريطة: اسم عمود النموذج (CSV) → اسم/تحويل حقل في Patient
# يمكن استخدام callable للحقول التي تحتاج تحويل (مثل Sex, Age)
def _sex_from_patient(p: Patient) -> float:
    # BRFSS: غالبًا Male=1, Female=0
    return 1.0 if (p.sex == "M") else 0.0

def _age_from_patient(p: Patient) -> float:
    # في التدريب نستخدم "Age" (فئات 1..13)، ونخزّن في الموديل age_group بنفس النطاق
    return float(p.age_group or 0)

# الحقول المباشرة: نستخدم getattr ثم coercion إلى float
FEATURE_MAP: Dict[str, Any] = {
    "HighBP":               lambda p: p.high_bp,
    "HighChol":             lambda p: p.high_chol,
    "CholCheck":            lambda p: p.chol_check,
    "BMI":                  lambda p: p.bmi,
    "Smoker":               lambda p: p.smoker,
    "Stroke":               lambda p: p.stroke,
    "HeartDiseaseorAttack": lambda p: p.heart_disease_or_attack,
    "PhysActivity":         lambda p: p.phys_activity,
    "Fruits":               lambda p: p.fruits,
    "Veggies":              lambda p: p.veggies,
    "HvyAlcoholConsump":    lambda p: p.hvy_alcohol_consump,
    "AnyHealthcare":        lambda p: p.any_healthcare,
    "NoDocbcCost":          lambda p: p.no_doc_bc_cost,
    "GenHlth":              lambda p: p.gen_hlth,
    "MentHlth":             lambda p: p.ment_hlth,
    "PhysHlth":             lambda p: p.phys_hlth,
    "DiffWalk":             lambda p: p.diff_walk,
    "Sex":                  _sex_from_patient,
    "Age":                  _age_from_patient,
    "Education":            lambda p: p.education,
    "Income":               lambda p: p.income,
}

def _ensure_feature_order() -> List[str]:
    """
    يرجع ترتيب الميزات كما حُفِظ في meta['features'] (إن وُجد)،
    وإلا يستخدم DEFAULT_MODEL_FEATURES. يُخزّن النتيجة مؤقتًا.
    """
    global _feature_order
    if _feature_order is not None:
        return _feature_order

    feats = None
    if isinstance(_meta, dict):
        feats = _meta.get("features")

    if isinstance(feats, list) and all(isinstance(x, str) for x in feats):
        _feature_order = list(feats)
    else:
        _feature_order = list(DEFAULT_MODEL_FEATURES)

    # تحذير إن وُجدت ميزات غير معروفة لدينا
    unknown = [f for f in _feature_order if f not in FEATURE_MAP]
    if unknown:
        logger.warning("Unknown features in meta: %s", unknown)

    return _feature_order

# ------------------------------------------------------------------ #
#                    تحويل Patient → متجه ميزات                       #
# ------------------------------------------------------------------ #
def _coerce_float(v: Any) -> float:
    if v in (None, "", False):
        return 0.0
    try:
        return float(v)
    except Exception:
        return 0.0

def patient_to_feature_dict(p: Patient) -> Dict[str, float]:
    """
    يعيد قاموس {feature_name: value} وفق ترتيب ميزات النموذج.
    مفيد للتشخيص والاختبارات.
    """
    order = _ensure_feature_order()
    out: Dict[str, float] = {}
    for feat in order:
        fn = FEATURE_MAP.get(feat)
        try:
            raw = fn(p) if callable(fn) else getattr(p, fn)  # عادةً callable
        except Exception:
            raw = None
        out[feat] = _coerce_float(raw)
    return out

def _patient_to_vector(p: Patient) -> np.ndarray:
    order = _ensure_feature_order()
    vals: List[float] = []
    for feat in order:
        fn = FEATURE_MAP.get(feat)
        try:
            raw = fn(p) if callable(fn) else getattr(p, fn)
        except Exception:
            raw = None
        vals.append(_coerce_float(raw))
    X = np.asarray(vals, dtype=np.float32).reshape(1, -1)
    return X

# ------------------------------------------------------------------ #
#                        واجهات التنبؤ والحفظ                         #
# ------------------------------------------------------------------ #
def quick_predict(patient: Patient) -> Dict[str, Any]:
    """
    يُعيد:
      {"label": int, "proba": {"0": float, "1": float, "2": float}}
    دون تعديل قاعدة البيانات.
    """
    model = _get_model()
    X = _patient_to_vector(patient)

    # label
    try:
        label = int(model.predict(X)[0])
    except Exception as exc:
        raise RuntimeError(f"Model.predict error: {exc}") from exc

    # proba
    try:
        proba_arr = model.predict_proba(X)[0]  # type: ignore[attr-defined]
    except AttributeError as exc:
        raise RuntimeError("Model lacks predict_proba") from exc

    proba = {str(i): float(p) for i, p in enumerate(proba_arr)}
    return {"label": label, "proba": proba}

def predict_and_save(patient: Patient) -> int:
    """
    يجري التنبؤ ويحفظ:
      - diabetes_prediction: الفئة المتنبأ بها
      - prediction_proba: احتمالات الفئات {"0": p0, "1": p1, "2": p2}
    لا يُعدّل diabetes_status (الحقيقة السريرية) إلا إذا OVERWRITE_STATUS=True.
    """
    result = quick_predict(patient)
    label: int = int(result["label"])
    proba: Dict[str, float] = {k: round(float(v), 4) for k, v in result["proba"].items()}

    update_fields: List[str] = ["diabetes_prediction", "prediction_proba"]
    patient.diabetes_prediction = label
    patient.prediction_proba = proba

    if OVERWRITE_STATUS:
        # اختياري: نسخ التنبؤ إلى الحالة السريرية (غير مفضّل عادةً)
        patient.diabetes_status = label
        update_fields.append("diabetes_status")

    patient.save(update_fields=update_fields)

    try:
        lbl = DiabetesStatus(label).label
    except Exception:
        lbl = str(label)
    logger.debug(
        "[%s] Patient %s → %s (proba=%s)",
        MODEL_NAME, patient.pk, lbl, patient.prediction_proba
    )
    return label

# ------------------------------------------------------------------ #
#                        (اختياري) تنبؤ جماعي                        #
# ------------------------------------------------------------------ #
def bulk_predict_and_save(qs: Sequence[Patient]) -> Tuple[int, int]:
    """
    يُحدّث مجموعة من المرضى. يُعيد (عدد الناجحين، عدد الأخطاء).
    ملاحظة: يحمّل النموذج مرة واحدة ويستخدمه لكل السجلات.
    """
    _get_model()  # يضمن تهيئة النموذج والميتا والميزات
    ok = 0
    err = 0
    for p in qs:
        try:
            predict_and_save(p)
            ok += 1
        except Exception as exc:  # pragma: no cover
            logger.warning("Predict failed for Patient %s: %s", getattr(p, "pk", "?"), exc)
            err += 1
    return ok, err
