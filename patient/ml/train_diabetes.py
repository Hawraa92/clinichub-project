"""
patient/ml/train_diabetes.py
Refactor 06-Aug-2025
يدعم تدريب DT | RF | GB | XGB على بيانات BRFSS متعددة الفئات (0 / 1 / 2).

المدخلات الافتراضية:
    CSV: diabetes_multiclass.csv (بنفس المجلد)
المخرجات:
    diabetes_<MODEL>.joblib
    diabetes_<MODEL>_meta.json
    diabetes_<MODEL>_report.json
    diabetes_<MODEL>_confusion.csv
    diabetes_<MODEL>_confusion_normalized.csv

التشغيل:
    python patient/ml/train_diabetes.py --model all
    python patient/ml/train_diabetes.py --model XGB --test-size 0.2 --smote
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Dict, Tuple, List, Any

import joblib
import numpy as np
import pandas as pd
from imblearn.over_sampling import SMOTE
from sklearn import __version__ as sklearn_version
from sklearn.metrics import (
    classification_report,
    confusion_matrix,
    f1_score,
    accuracy_score,
)
from sklearn.model_selection import train_test_split, StratifiedKFold, cross_val_score
from sklearn.tree import DecisionTreeClassifier
from sklearn.ensemble import RandomForestClassifier, GradientBoostingClassifier

try:
    from xgboost import XGBClassifier  # type: ignore
    _HAS_XGB = True
except Exception:  # pragma: no cover
    XGBClassifier = None
    _HAS_XGB = False

try:
    import imblearn  # type: ignore
    imblearn_version = getattr(imblearn, "__version__", "unknown")
except Exception:
    imblearn_version = "unknown"


# ------------------------------------------------------------------ #
#                        مسارات وخصائص                               #
# ------------------------------------------------------------------ #
BASE_DIR = Path(__file__).resolve().parent
DEFAULT_CSV = BASE_DIR / "diabetes_multiclass.csv"

# أعمدة BRFSS الشائعة (مطابقة لملفك السابق)
FEATURES: List[str] = [
    "HighBP", "HighChol", "CholCheck", "BMI", "Smoker", "Stroke",
    "HeartDiseaseorAttack", "PhysActivity", "Fruits", "Veggies",
    "HvyAlcoholConsump", "AnyHealthcare", "NoDocbcCost", "GenHlth",
    "MentHlth", "PhysHlth", "DiffWalk", "Sex", "Age", "Education", "Income",
]
TARGET = "Diabetes_012"
CLASS_LABELS = {0: "Healthy", 1: "Prediabetic", 2: "Diabetic"}
RANDOM_STATE = 42


# ------------------------------------------------------------------ #
#                         وظائف مساعدة                               #
# ------------------------------------------------------------------ #
def _build_models(args) -> Dict[str, Any]:
    models: Dict[str, Any] = {}
    want = args.model.upper()

    if want in ("DT", "ALL"):
        models["DT"] = DecisionTreeClassifier(
            max_depth=None,
            class_weight="balanced",
            random_state=RANDOM_STATE,
        )

    if want in ("RF", "ALL"):
        models["RF"] = RandomForestClassifier(
            n_estimators=300,
            class_weight="balanced",
            n_jobs=-1,
            random_state=RANDOM_STATE,
        )

    if want in ("GB", "ALL"):
        models["GB"] = GradientBoostingClassifier(
            random_state=RANDOM_STATE,
        )

    if want in ("XGB", "ALL") and _HAS_XGB:
        models["XGB"] = XGBClassifier(
            objective="multi:softprob",
            num_class=3,
            eval_metric="mlogloss",
            learning_rate=0.05,
            max_depth=6,
            n_estimators=400,
            subsample=0.8,
            colsample_bytree=1.0,
            reg_lambda=1.0,
            random_state=RANDOM_STATE,
            tree_method="hist",  # أسرع غالباً
        )

    if want == "XGB" and not _HAS_XGB:
        raise RuntimeError("xgboost غير مثبت. ثبّت الحزمة أو اختر نموذجًا آخر.")

    if not models:
        raise ValueError(f"نموذج غير معروف: {args.model}. استخدم: DT | RF | GB | XGB | ALL")
    return models


def _split(df: pd.DataFrame, test_size: float, valid_size: float, smote: bool):
    # تحقّق الأعمدة
    missing = sorted(set(FEATURES) - set(df.columns))
    if missing:
        raise ValueError(f"❌ أعمدة ناقصة في CSV: {missing}")
    if TARGET not in df.columns:
        raise ValueError("❌ عمود الهدف مفقود")

    X = df[FEATURES].copy()
    y = df[TARGET].copy()

    # تنظيف أنواع البيانات
    X = X.fillna(0)
    for col in X.columns:
        # نتأكد أنها رقمية
        X[col] = pd.to_numeric(X[col], errors="coerce").fillna(0)

    # الأنواع النهائية
    X = X.astype("float32")
    y = pd.to_numeric(y, errors="raise").astype("int8")

    # Train/Valid/Test: أولاً نفصل test
    X_tmp, X_te, y_tmp, y_te = train_test_split(
        X, y, test_size=test_size, stratify=y, random_state=RANDOM_STATE
    )

    # ثم نفصل valid من المتبقي
    valid_rel = valid_size / (1.0 - test_size)
    X_tr, X_va, y_tr, y_va = train_test_split(
        X_tmp, y_tmp, test_size=valid_rel, stratify=y_tmp, random_state=RANDOM_STATE
    )

    # موازنة SMOTE على train فقط
    if smote:
        X_tr, y_tr = SMOTE(random_state=RANDOM_STATE, k_neighbors=3).fit_resample(X_tr, y_tr)

    return X_tr, X_va, X_te, y_tr, y_va, y_te


def _evaluate_and_save(
    name: str,
    model,
    X_tr: pd.DataFrame,
    y_tr: pd.Series,
    X_va: pd.DataFrame,
    y_va: pd.Series,
    X_te: pd.DataFrame,
    y_te: pd.Series,
    out_dir: Path,
) -> Tuple[Path, Path]:
    """
    يدرب، يقيم (CV + Valid + Test)، ثم يحفظ النموذج والميتا والتقارير.
    """
    # تدريب
    model.fit(X_tr, y_tr)

    # --- Cross-Validation (Macro F1) على train (قبل valid/test) ---
    cv = StratifiedKFold(n_splits=5, shuffle=True, random_state=RANDOM_STATE)
    cv_scores = cross_val_score(model, X_tr, y_tr, scoring="f1_macro", cv=cv, n_jobs=-1)
    cv_mean = float(np.mean(cv_scores))
    cv_std = float(np.std(cv_scores))

    # --- Valid ---
    va_pred = model.predict(X_va)
    va_acc = accuracy_score(y_va, va_pred)
    va_f1_macro = f1_score(y_va, va_pred, average="macro")

    # --- Test ---
    te_pred = model.predict(X_te)
    te_acc = accuracy_score(y_te, te_pred)
    te_f1_macro = f1_score(y_te, te_pred, average="macro")
    te_report = classification_report(
        y_te,
        te_pred,
        digits=4,
        target_names=[CLASS_LABELS[i] for i in sorted(CLASS_LABELS)],
        zero_division=0,
        output_dict=True,
    )
    te_cm = confusion_matrix(y_te, te_pred, labels=[0, 1, 2])
    te_cm_norm = confusion_matrix(y_te, te_pred, labels=[0, 1, 2], normalize="true")

    # طباعة موجز
    print(f"\n=== {name} ===")
    print(f"CV Macro-F1 (5-fold): {cv_mean:.4f} ± {cv_std:.4f}")
    print(f"Valid Acc: {va_acc:.4f} | Valid Macro-F1: {va_f1_macro:.4f}")
    print(f"Test  Acc: {te_acc:.4f} | Test  Macro-F1: {te_f1_macro:.4f}")

    # --- حفظ النموذج ---
    out_dir.mkdir(parents=True, exist_ok=True)
    model_path = out_dir / f"diabetes_{name}.joblib"
    joblib.dump(model, model_path, compress=("lzma", 3))

    # --- حفظ الميتاداتا ---
    meta_path = out_dir / f"diabetes_{name}_meta.json"
    meta: Dict[str, Any] = {
        "features": FEATURES,
        "class_labels": CLASS_LABELS,
        "sklearn_version": sklearn_version,
        "imblearn_version": imblearn_version,
        "cv_macro_f1_mean": cv_mean,
        "cv_macro_f1_std": cv_std,
        "valid_accuracy": float(va_acc),
        "valid_macro_f1": float(va_f1_macro),
        "test_accuracy": float(te_acc),
        "test_macro_f1": float(te_f1_macro),
        "target": TARGET,
        "model_name": name,
    }

    # Feature importances إن توفرت
    try:
        if hasattr(model, "feature_importances_"):
            meta["feature_importances"] = {f: float(v) for f, v in zip(FEATURES, model.feature_importances_)}
    except Exception:
        pass

    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2))

    # --- حفظ التقارير ---
    report_path = out_dir / f"diabetes_{name}_report.json"
    report_payload = {
        "classification_report": te_report,  # يحوي per-class precision/recall/f1/support
    }
    report_path.write_text(json.dumps(report_payload, ensure_ascii=False, indent=2))

    # --- حفظ مصفوفات الالتباس ---
    cm_path = out_dir / f"diabetes_{name}_confusion.csv"
    cmn_path = out_dir / f"diabetes_{name}_confusion_normalized.csv"
    pd.DataFrame(te_cm, index=["true_0", "true_1", "true_2"], columns=["pred_0", "pred_1", "pred_2"]).to_csv(cm_path, index=True)
    pd.DataFrame(te_cm_norm, index=["true_0", "true_1", "true_2"], columns=["pred_0", "pred_1", "pred_2"]).to_csv(cmn_path, index=True)

    return model_path, meta_path


# ------------------------------------------------------------------ #
#                              main()                                #
# ------------------------------------------------------------------ #
def main() -> None:
    parser = argparse.ArgumentParser(description="Train multiclass diabetes models on BRFSS-like data.")
    parser.add_argument("--csv", type=str, default=str(DEFAULT_CSV), help="CSV path (default: diabetes_multiclass.csv)")
    parser.add_argument("--model", type=str, default="ALL", help="DT | RF | GB | XGB | ALL")
    parser.add_argument("--test-size", type=float, default=0.20, help="Test size fraction (default 0.20)")
    parser.add_argument("--valid-size", type=float, default=0.10, help="Validation size fraction from full data (default 0.10)")
    parser.add_argument("--smote", action="store_true", help="Apply SMOTE on train split")
    parser.add_argument("--out-dir", type=str, default=str(BASE_DIR), help="Output directory (default: current dir)")
    args = parser.parse_args()

    csv_path = Path(args.csv)
    if not csv_path.exists():
        raise FileNotFoundError(f"لم يتم العثور على ملف CSV: {csv_path}")

    # تحميل البيانات
    df = pd.read_csv(csv_path)

    # تقسيم البيانات
    X_tr, X_va, X_te, y_tr, y_va, y_te = _split(df, test_size=args.test_size, valid_size=args.valid_size, smote=args.smote)

    # بناء النماذج المطلوبة
    models = _build_models(args)
    out_dir = Path(args.out_dir)

    # تدريب وتقييم وحفظ
    for name, model in models.items():
        mp, meta = _evaluate_and_save(name, model, X_tr, y_tr, X_va, y_va, X_te, y_te, out_dir)
        print(f"✅ Saved ➜ {mp.name}  |  meta ➜ {meta.name}")


if __name__ == "__main__":
    main()
