"""ML experiments scaffold — Phase 12e (offline only, pas branché en prod).

Framework de comparaison de modèles pour backtests futurs. Ne remplace pas
bot/predictor.py tant qu'un walk-forward n'a pas prouvé un edge vs le logit
actuel (même prudence que intelligence_layer Phase 2).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence

# Features alignées sur config.FEATURE_ORDER + signaux ELO/surface dérivés.
FEATURE_COLUMNS: List[str] = [
    "serve_diff",
    "return1_diff",
    "return2_diff",
    "recent_diff",
    "elo_diff_norm",
    "surface_elo_diff_norm",
    "h2h_win_rate",
    "fatigue_diff",
    "opponent_quality_diff",
    "clutch_bp_save_diff",
    "steam_move_aligned",
    "implied_prob_diff",
]

SUPPORTED_MODELS: List[str] = ["logistic", "random_forest", "xgboost"]


@dataclass
class ModelSpec:
    name: str
    params: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ExperimentResult:
    model: str
    accuracy: float
    log_loss: float
    brier: float
    roi_simulated: Optional[float] = None
    n_samples: int = 0
    notes: str = ""


def default_model_grid() -> List[ModelSpec]:
    """Grille par défaut pour comparaison offline."""
    return [
        ModelSpec("logistic", {"C": 1.0, "max_iter": 500}),
        ModelSpec("random_forest", {"n_estimators": 200, "max_depth": 6}),
        ModelSpec("xgboost", {"n_estimators": 150, "max_depth": 4, "learning_rate": 0.05}),
    ]


def build_feature_matrix(rows: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """Stub : transforme des lignes match en matrice X (à brancher sur db/backtest).

    Chaque `row` attend des clés optionnelles correspondant à FEATURE_COLUMNS.
    Retourne {"columns": FEATURE_COLUMNS, "X": list, "y": list} pour sklearn/xgb.
    """
    x_rows: List[List[float]] = []
    y_rows: List[int] = []
    for row in rows:
        x_rows.append([float(row.get(c, 0.0)) for c in FEATURE_COLUMNS])
        if "label" in row:
            y_rows.append(int(row["label"]))
    return {"columns": FEATURE_COLUMNS, "X": x_rows, "y": y_rows if y_rows else None}


def compare_models(
    rows: Sequence[Dict[str, Any]],
    specs: Optional[List[ModelSpec]] = None,
) -> List[ExperimentResult]:
    """Compare logistic / RF / XGBoost sur les mêmes données (offline).

    Implémentation minimale : sans sklearn installé, renvoie des placeholders
    documentés pour ne pas casser l'import en prod.
    """
    specs = specs or default_model_grid()
    bundle = build_feature_matrix(rows)
    n = len(bundle["X"])
    if n == 0:
        return []

    results: List[ExperimentResult] = []
    try:
        import numpy as np  # noqa: F401
        from sklearn.linear_model import LogisticRegression
        from sklearn.ensemble import RandomForestClassifier
        from sklearn.metrics import accuracy_score, log_loss, brier_score_loss
    except ImportError:
        for spec in specs:
            results.append(ExperimentResult(
                model=spec.name,
                accuracy=0.0,
                log_loss=0.0,
                brier=0.0,
                n_samples=n,
                notes="scikit-learn non installé — stub Phase 12e",
            ))
        return results

    import numpy as np
    from sklearn.linear_model import LogisticRegression
    from sklearn.ensemble import RandomForestClassifier
    from sklearn.metrics import accuracy_score, brier_score_loss, log_loss
    from sklearn.model_selection import train_test_split

    X = np.array(bundle["X"])
    y = np.array(bundle["y"] or [0] * n)
    if len(set(y)) < 2:
        return [ExperimentResult(
            model="none", accuracy=0.0, log_loss=0.0, brier=0.0, n_samples=n,
            notes="échantillon sans variance de label",
        )]

    x_train, x_test, y_train, y_test = train_test_split(
        X, y, test_size=0.25, random_state=42, stratify=y,
    )

    for spec in specs:
        if spec.name == "logistic":
            clf = LogisticRegression(**spec.params)
        elif spec.name == "random_forest":
            clf = RandomForestClassifier(**spec.params, random_state=42)
        elif spec.name == "xgboost":
            try:
                from xgboost import XGBClassifier
                clf = XGBClassifier(**spec.params, eval_metric="logloss")
            except ImportError:
                results.append(ExperimentResult(
                    model=spec.name, accuracy=0.0, log_loss=0.0, brier=0.0,
                    n_samples=n, notes="xgboost non installé",
                ))
                continue
        else:
            continue
        clf.fit(x_train, y_train)
        proba = clf.predict_proba(x_test)[:, 1]
        pred = (proba >= 0.5).astype(int)
        results.append(ExperimentResult(
            model=spec.name,
            accuracy=round(float(accuracy_score(y_test, pred)), 4),
            log_loss=round(float(log_loss(y_test, proba)), 4),
            brier=round(float(brier_score_loss(y_test, proba)), 4),
            n_samples=len(y_test),
        ))
    return results
