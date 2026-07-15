"""Entraînement et comparaison de modèles ML hors-ligne.

Compare LogisticRegression, RandomForest et XGBoost sur un hold-out chronologique.
scikit-learn et xgboost sont optionnels (try/except) — le module reste importable
sans eux pour les tests de dataset.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from .dataset_builder import Dataset, build_dataset
from .evaluate import evaluate_holdout
from .features import FEATURE_NAMES, rows_to_matrix

_SKLEARN_OK = False
_XGB_OK = False

try:
    from sklearn.ensemble import RandomForestClassifier
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import StandardScaler

    _SKLEARN_OK = True
except ImportError:
    LogisticRegression = None  # type: ignore
    RandomForestClassifier = None  # type: ignore
    Pipeline = None  # type: ignore
    StandardScaler = None  # type: ignore

try:
    from xgboost import XGBClassifier

    _XGB_OK = True
except ImportError:
    XGBClassifier = None  # type: ignore


def _require_sklearn() -> None:
    if not _SKLEARN_OK:
        raise ImportError(
            "scikit-learn requis pour l'entraînement offline. "
            "Installez : pip install scikit-learn"
        )


def _predict_proba(model: Any, X: List[List[float]]) -> List[float]:
    if hasattr(model, "predict_proba"):
        return [float(p[1]) for p in model.predict_proba(X)]
    preds = model.predict(X)
    return [float(p) for p in preds]


def compare_models(
    X_train: List[List[float]],
    y_train: List[int],
    X_test: List[List[float]],
    y_test: List[int],
    feature_names: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Entraîne et compare LR / RF / XGBoost ; renvoie métriques hold-out."""
    _require_sklearn()
    names = feature_names or FEATURE_NAMES
    results: Dict[str, Any] = {
        "feature_names": names,
        "n_train": len(y_train),
        "n_test": len(y_test),
        "models": {},
        "sklearn_available": _SKLEARN_OK,
        "xgboost_available": _XGB_OK,
    }

    candidates: List[Tuple[str, Any]] = [
        (
            "logistic_regression",
            Pipeline([
                ("scaler", StandardScaler()),
                ("clf", LogisticRegression(max_iter=1000, random_state=42)),
            ]),
        ),
        (
            "random_forest",
            RandomForestClassifier(
                n_estimators=100, max_depth=8, random_state=42, n_jobs=-1,
            ),
        ),
    ]
    if _XGB_OK and XGBClassifier is not None:
        candidates.append((
            "xgboost",
            XGBClassifier(
                n_estimators=100, max_depth=4, learning_rate=0.1,
                eval_metric="logloss", random_state=42, verbosity=0,
            ),
        ))

    best_auc = -1.0
    best_name = None

    for name, model in candidates:
        try:
            model.fit(X_train, y_train)
            y_pred = [int(v) for v in model.predict(X_test)]
            y_proba = _predict_proba(model, X_test)
            metrics = evaluate_holdout(y_test, y_pred, y_proba)
            entry: Dict[str, Any] = {"metrics": metrics, "fitted": True}
            if name == "random_forest" and hasattr(model, "feature_importances_"):
                entry["feature_importance"] = {
                    names[i]: round(float(model.feature_importances_[i]), 4)
                    for i in range(len(names))
                }
            results["models"][name] = entry
            auc = metrics.get("auc")
            if auc is not None and auc > best_auc:
                best_auc = auc
                best_name = name
        except Exception as exc:
            results["models"][name] = {"fitted": False, "error": str(exc)}

    results["best_by_auc"] = best_name
    return results


def train_offline(
    test_fraction: Optional[float] = None,
    dataset: Optional[Dataset] = None,
) -> Dict[str, Any]:
    """Pipeline complet : build_dataset → compare_models."""
    ds = dataset or build_dataset(test_fraction=test_fraction)
    X_train, y_train, names = ds.matrix("train")
    X_test, y_test, _ = ds.matrix("test")
    if not y_train or not y_test:
        return {
            "error": "Split train/test vide — pas assez de matchs.",
            "meta": ds.meta,
        }
    report = compare_models(X_train, y_train, X_test, y_test, names)
    report["meta"] = ds.meta
    return report


def main() -> None:
    """Point d'entrée CLI : python -m bot.ml_prep.train"""
    import json

    report = train_offline()
    print(json.dumps(report, indent=2, default=str))


if __name__ == "__main__":
    main()
