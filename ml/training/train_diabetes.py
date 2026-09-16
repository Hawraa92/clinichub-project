# -*- coding: utf-8 -*-
"""
ml/training/train_diabetes.py
Binary Diabetes Training (Diabetic vs Non-Diabetic)

Target mapping:
- Diabetes = 1 if Diabetes_012 == 2
- Diabetes = 0 if Diabetes_012 in {0, 1}

Default paths (from project root):
- CSV: ml/data/diabetes_multiclass.csv
- Artifacts: ml/artifacts/
- Reports: ml/reports/

Run examples:
  python ml/training/train_diabetes.py --model RF
  python ml/training/train_diabetes.py --model RF --smote
  python ml/training/train_diabetes.py --model DT
  python ml/training/train_diabetes.py --model DT --smote --csv ml/data/diabetes_smote_sample.csv
  python ml/training/train_diabetes.py --model ALL --test-size 0.2 --valid-size 0.1

Speed controls:
  python ml/training/train_diabetes.py --model RF --rf-estimators 200 --cv-splits 3 --cv-jobs 1
  python ml/training/train_diabetes.py --model DT --smote --no-cv   (fast)

Why Windows patch?
Some Windows setups hang when joblib/loky tries to detect physical CPU cores (subprocess call).
This script patches loky.cpu_count to avoid the physical-core detection path.
"""

from __future__ import annotations

import os

# ------------------------------------------------------------------
# Windows stability patch (prevents loky physical-core detection hang)
# ------------------------------------------------------------------
os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("MKL_NUM_THREADS", "1")
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("NUMEXPR_NUM_THREADS", "1")

import joblib  # noqa: E402

try:
    from joblib.externals.loky.backend import context as loky_context  # type: ignore  # noqa: E402

    def _loky_safe_cpu_count(only_physical_cores: bool = True) -> int:
        # Ignore "physical cores" detection on Windows; just use logical CPUs.
        return int(os.cpu_count() or 1)

    loky_context.cpu_count = _loky_safe_cpu_count  # type: ignore[attr-defined]
except Exception:
    # If loky isn't available for some reason, continue; script may still work.
    pass

# ------------------------------------------------------------------
# Standard imports
# ------------------------------------------------------------------
import argparse  # noqa: E402
import json  # noqa: E402
from pathlib import Path  # noqa: E402
from typing import Dict, List, Any, Optional, Tuple  # noqa: E402

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from imblearn.over_sampling import SMOTE  # noqa: E402
from sklearn import __version__ as sklearn_version  # noqa: E402
from sklearn.metrics import (  # noqa: E402
    classification_report,
    confusion_matrix,
    f1_score,
    accuracy_score,
    roc_auc_score,
    average_precision_score,
)
from sklearn.model_selection import train_test_split, StratifiedKFold, cross_val_score  # noqa: E402
from sklearn.tree import DecisionTreeClassifier  # noqa: E402
from sklearn.ensemble import RandomForestClassifier, GradientBoostingClassifier  # noqa: E402

try:
    from xgboost import XGBClassifier  # type: ignore  # noqa: E402
    _HAS_XGB = True
except Exception:  # pragma: no cover
    XGBClassifier = None
    _HAS_XGB = False

try:
    import imblearn  # type: ignore  # noqa: E402
    imblearn_version = getattr(imblearn, "__version__", "unknown")
except Exception:
    imblearn_version = "unknown"


# ------------------------------------------------------------------ #
# Paths
# ------------------------------------------------------------------ #
TRAINING_DIR = Path(__file__).resolve().parent          # .../ml/training
ML_DIR = TRAINING_DIR.parent                            # .../ml
DATA_DIR = ML_DIR / "data"
ARTIFACTS_DIR = ML_DIR / "artifacts"
REPORTS_DIR = ML_DIR / "reports"

DEFAULT_CSV = DATA_DIR / "diabetes_multiclass.csv"

# ------------------------------------------------------------------ #
# Dataset schema
# ------------------------------------------------------------------ #
FEATURES: List[str] = [
    "HighBP", "HighChol", "CholCheck", "BMI", "Smoker", "Stroke",
    "HeartDiseaseorAttack", "PhysActivity", "Fruits", "Veggies",
    "HvyAlcoholConsump", "AnyHealthcare", "NoDocbcCost", "GenHlth",
    "MentHlth", "PhysHlth", "DiffWalk", "Sex", "Age", "Education", "Income",
]
TARGET_RAW = "Diabetes_012"  # original in CSV
TARGET_BIN = "DiabetesBinary"

CLASS_LABELS = {0: "NonDiabetic", 1: "Diabetic"}
RANDOM_STATE = 42


# ------------------------------------------------------------------ #
# Helpers
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
        # IMPORTANT (Windows): keep n_jobs=1 to avoid spawn storms + instability
        models["RF"] = RandomForestClassifier(
            n_estimators=args.rf_estimators,
            class_weight="balanced",
            n_jobs=1,
            random_state=RANDOM_STATE,
        )

    if want in ("GB", "ALL"):
        models["GB"] = GradientBoostingClassifier(
            random_state=RANDOM_STATE,
        )

    if want in ("XGB", "ALL") and _HAS_XGB:
        models["XGB"] = XGBClassifier(
            objective="binary:logistic",
            eval_metric="logloss",
            learning_rate=0.05,
            max_depth=6,
            n_estimators=500,
            subsample=0.8,
            colsample_bytree=1.0,
            reg_lambda=1.0,
            random_state=RANDOM_STATE,
            tree_method="hist",
        )

    if want == "XGB" and not _HAS_XGB:
        raise RuntimeError("xgboost غير مثبت. ثبت الحزمة أو اختر موديل آخر (DT/RF/GB).")

    if not models:
        raise ValueError(f"موديل غير معروف: {args.model}. استخدم: DT | RF | GB | XGB | ALL")
    return models


def _make_binary_target(df: pd.DataFrame) -> pd.Series:
    if TARGET_RAW not in df.columns:
        raise ValueError(f"عمود الهدف غير موجود: {TARGET_RAW}")
    y_raw = pd.to_numeric(df[TARGET_RAW], errors="raise").astype("int8")
    # 1 if == 2 else 0
    return (y_raw == 2).astype("int8")


def _split(df: pd.DataFrame, test_size: float, valid_size: float, smote: bool):
    missing = sorted(set(FEATURES) - set(df.columns))
    if missing:
        raise ValueError(f"أعمدة ناقصة في CSV: {missing}")

    X = df[FEATURES].copy()
    y = _make_binary_target(df)

    # تنظيف وتحويل
    X = X.fillna(0)
    for col in X.columns:
        X[col] = pd.to_numeric(X[col], errors="coerce").fillna(0)
    X = X.astype("float32")

    # Train/Valid/Test
    X_tmp, X_te, y_tmp, y_te = train_test_split(
        X, y, test_size=test_size, stratify=y, random_state=RANDOM_STATE
    )
    valid_rel = valid_size / (1.0 - test_size)
    X_tr, X_va, y_tr, y_va = train_test_split(
        X_tmp, y_tmp, test_size=valid_rel, stratify=y_tmp, random_state=RANDOM_STATE
    )

    # SMOTE on train only
    if smote:
        X_tr, y_tr = SMOTE(random_state=RANDOM_STATE, k_neighbors=3).fit_resample(X_tr, y_tr)

    return X_tr, X_va, X_te, y_tr, y_va, y_te


def _safe_predict_proba(model, X) -> Optional[np.ndarray]:
    if hasattr(model, "predict_proba"):
        try:
            return model.predict_proba(X)[:, 1]
        except Exception:
            return None
    return None


def _dataset_tag_from_csv(csv_path: Path) -> str:
    tag = csv_path.stem.strip()
    tag = tag.replace(" ", "_")
    # avoid too-long filenames
    return tag[:40] if len(tag) > 40 else tag


def _evaluate_and_save(
    name: str,
    model,
    X_tr: pd.DataFrame,
    y_tr: pd.Series,
    X_va: pd.DataFrame,
    y_va: pd.Series,
    X_te: pd.DataFrame,
    y_te: pd.Series,
    save_confusion: bool,
    cv_splits: int,
    cv_jobs: int,
    smote_used: bool,
    no_cv: bool,
    dataset_tag: str,
) -> None:
    # Train
    model.fit(X_tr, y_tr)

    # CV (F1)
    cv_mean: Optional[float] = None
    cv_std: Optional[float] = None
    if not no_cv:
        if cv_splits < 2:
            raise ValueError("--cv-splits لازم يكون >= 2 أو استخدم --no-cv")
        cv = StratifiedKFold(n_splits=cv_splits, shuffle=True, random_state=RANDOM_STATE)
        cv_scores = cross_val_score(model, X_tr, y_tr, scoring="f1", cv=cv, n_jobs=cv_jobs)
        cv_mean = float(np.mean(cv_scores))
        cv_std = float(np.std(cv_scores))

    # Valid
    va_pred = model.predict(X_va)
    va_acc = float(accuracy_score(y_va, va_pred))
    va_f1 = float(f1_score(y_va, va_pred))

    # Test
    te_pred = model.predict(X_te)
    te_acc = float(accuracy_score(y_te, te_pred))
    te_f1 = float(f1_score(y_te, te_pred))

    te_report = classification_report(
        y_te,
        te_pred,
        digits=4,
        target_names=[CLASS_LABELS[0], CLASS_LABELS[1]],
        zero_division=0,
        output_dict=True,
    )

    te_cm = confusion_matrix(y_te, te_pred, labels=[0, 1])
    te_cm_norm = confusion_matrix(y_te, te_pred, labels=[0, 1], normalize="true")

    # Prob metrics
    proba = _safe_predict_proba(model, X_te)
    roc_auc = float(roc_auc_score(y_te, proba)) if proba is not None else None
    pr_auc = float(average_precision_score(y_te, proba)) if proba is not None else None

    tag = "smote" if smote_used else "base"

    print(f"\n=== {name} (BINARY | {tag} | {dataset_tag}) ===")
    if cv_mean is not None and cv_std is not None:
        print(f"CV F1 ({cv_splits}-fold): {cv_mean:.4f} ± {cv_std:.4f}")
    else:
        print("CV: skipped (--no-cv)")

    print(f"Valid Acc: {va_acc:.4f} | Valid F1: {va_f1:.4f}")
    print(f"Test  Acc: {te_acc:.4f} | Test  F1: {te_f1:.4f}")
    if roc_auc is not None and pr_auc is not None:
        print(f"ROC-AUC: {roc_auc:.4f} | PR-AUC: {pr_auc:.4f}")

    # Ensure dirs
    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)

    # Filenames (avoid overwrite across datasets)
    base_name = f"diabetes_binary_{name}_{tag}_{dataset_tag}"

    # Save model
    model_path = ARTIFACTS_DIR / f"{base_name}.joblib"
    joblib.dump(model, model_path, compress=("lzma", 3))

    # Save meta
    meta_path = ARTIFACTS_DIR / f"{base_name}_meta.json"
    meta: Dict[str, Any] = {
        "task": "binary_diabetes",
        "target_raw": TARGET_RAW,
        "target_binary": TARGET_BIN,
        "positive_definition": "1 if Diabetes_012 == 2 else 0",
        "features": FEATURES,
        "class_labels": CLASS_LABELS,
        "sklearn_version": sklearn_version,
        "imblearn_version": imblearn_version,
        "cv_f1_mean": cv_mean,
        "cv_f1_std": cv_std,
        "cv_splits": None if no_cv else cv_splits,
        "cv_jobs": None if no_cv else cv_jobs,
        "valid_accuracy": va_acc,
        "valid_f1": va_f1,
        "test_accuracy": te_acc,
        "test_f1": te_f1,
        "roc_auc": roc_auc,
        "pr_auc": pr_auc,
        "model_name": name,
        "tag": tag,
        "smote": smote_used,
        "dataset_tag": dataset_tag,
        "csv_used": str(dataset_tag),
    }

    try:
        if hasattr(model, "feature_importances_"):
            meta["feature_importances"] = {f: float(v) for f, v in zip(FEATURES, model.feature_importances_)}
    except Exception:
        pass

    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

    # Save report
    report_path = REPORTS_DIR / f"{base_name}_report.json"
    report_payload = {
        "classification_report": te_report,
        "confusion_matrix": te_cm.tolist(),
        "confusion_matrix_normalized": te_cm_norm.tolist(),
    }
    report_path.write_text(json.dumps(report_payload, ensure_ascii=False, indent=2), encoding="utf-8")

    # Optional confusion CSVs
    if save_confusion:
        cm_path = REPORTS_DIR / f"{base_name}_confusion.csv"
        cmn_path = REPORTS_DIR / f"{base_name}_confusion_normalized.csv"
        pd.DataFrame(te_cm, index=["true_0", "true_1"], columns=["pred_0", "pred_1"]).to_csv(cm_path, index=True)
        pd.DataFrame(te_cm_norm, index=["true_0", "true_1"], columns=["pred_0", "pred_1"]).to_csv(cmn_path, index=True)

    print(f"✅ Saved model:   {model_path}")
    print(f"✅ Saved meta:    {meta_path}")
    print(f"✅ Saved report:  {report_path}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Train BINARY diabetes models (Diabetic vs NonDiabetic).")
    parser.add_argument("--csv", type=str, default=str(DEFAULT_CSV), help="CSV path (default: ml/data/diabetes_multiclass.csv)")
    parser.add_argument("--model", type=str, default="RF", help="DT | RF | GB | XGB | ALL (default RF)")
    parser.add_argument("--test-size", type=float, default=0.20, help="Test size fraction (default 0.20)")
    parser.add_argument("--valid-size", type=float, default=0.10, help="Validation size fraction from full data (default 0.10)")
    parser.add_argument("--smote", action="store_true", help="Apply SMOTE on train split (binary)")
    parser.add_argument("--save-confusion", action="store_true", help="Also save confusion CSV files into ml/reports/")
    parser.add_argument("--cv-splits", type=int, default=3, help="CV folds (default 3)")
    parser.add_argument("--cv-jobs", type=int, default=1, help="CV n_jobs (default 1 for Windows stability)")
    parser.add_argument("--no-cv", action="store_true", help="Skip cross-validation completely (fast)")
    parser.add_argument("--rf-estimators", type=int, default=250, help="RF n_estimators (default 250)")
    args = parser.parse_args()

    csv_path = Path(args.csv)
    if not csv_path.exists():
        raise FileNotFoundError(f"لم يتم العثور على CSV: {csv_path}")

    df = pd.read_csv(csv_path)

    # Print basic distribution
    y_all = _make_binary_target(df)
    pos = int((y_all == 1).sum())
    neg = int((y_all == 0).sum())
    total = int(len(y_all))
    print(f"Dataset: {csv_path.name} | rows={total} | pos(diabetic)={pos} ({pos/total:.2%}) | neg={neg} ({neg/total:.2%})")

    X_tr, X_va, X_te, y_tr, y_va, y_te = _split(
        df,
        test_size=args.test_size,
        valid_size=args.valid_size,
        smote=args.smote,
    )

    models = _build_models(args)
    dataset_tag = _dataset_tag_from_csv(csv_path)

    for name, model in models.items():
        _evaluate_and_save(
            name=name,
            model=model,
            X_tr=X_tr,
            y_tr=y_tr,
            X_va=X_va,
            y_va=y_va,
            X_te=X_te,
            y_te=y_te,
            save_confusion=args.save_confusion,
            cv_splits=args.cv_splits,
            cv_jobs=args.cv_jobs,
            smote_used=args.smote,
            no_cv=args.no_cv,
            dataset_tag=dataset_tag,
        )


if __name__ == "__main__":
    main()
