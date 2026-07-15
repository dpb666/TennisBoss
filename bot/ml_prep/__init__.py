"""Préparation ML hors-ligne (Phase 12) — scaffold uniquement.

Ce package construit des matrices de features à partir de la base SQLite,
entraîne et compare des modèles classiques (LogisticRegression, RandomForest,
XGBoost) en local, et évalue accuracy / AUC / ROI simulé.

Ne modifie PAS predictor.py ni /api/predict. Dépendances optionnelles :
scikit-learn, xgboost (importées via try/except si absentes).
"""
from __future__ import annotations

from .dataset_builder import Dataset, build_dataset
from .evaluate import evaluate_holdout, simulate_roi
from .features import FEATURE_NAMES
from .train import compare_models, train_offline

__all__ = [
    "Dataset",
    "FEATURE_NAMES",
    "build_dataset",
    "compare_models",
    "evaluate_holdout",
    "simulate_roi",
    "train_offline",
]
