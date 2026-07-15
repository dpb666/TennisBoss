"""Évaluation hors-ligne : accuracy, AUC, simulation ROI sur hold-out."""
from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Sequence


def _require_sklearn_metrics():
    try:
        from sklearn.metrics import accuracy_score, roc_auc_score
        return accuracy_score, roc_auc_score
    except ImportError:
        return None, None


def accuracy(y_true: Sequence[int], y_pred: Sequence[int]) -> float:
    """Accuracy simple (fallback manuel si sklearn absent)."""
    acc_fn, _ = _require_sklearn_metrics()
    if acc_fn is not None:
        return float(acc_fn(y_true, y_pred))
    if not y_true:
        return float("nan")
    hits = sum(1 for t, p in zip(y_true, y_pred) if int(t) == int(p))
    return hits / len(y_true)


def auc_score(y_true: Sequence[int], y_proba: Sequence[float]) -> Optional[float]:
    """AUC ROC ; None si une seule classe ou sklearn absent."""
    if len(set(y_true)) < 2:
        return None
    _, auc_fn = _require_sklearn_metrics()
    if auc_fn is not None:
        try:
            return float(auc_fn(y_true, y_proba))
        except ValueError:
            return None
    # Fallback trapezoidal rudimentaire
    pairs = sorted(zip(y_proba, y_true), reverse=True)
    tp = fp = 0
    p_total = sum(y_true)
    n_total = len(y_true) - p_total
    if p_total == 0 or n_total == 0:
        return None
    auc = 0.0
    prev_fpr = prev_tpr = 0.0
    for prob, label in pairs:
        if label:
            tp += 1
        else:
            fp += 1
        tpr = tp / p_total
        fpr = fp / n_total
        auc += (fpr - prev_fpr) * (tpr + prev_tpr) / 2
        prev_fpr, prev_tpr = fpr, tpr
    return float(auc)


def simulate_roi(
    y_true: Sequence[int],
    y_proba: Sequence[float],
    odds_implied: Optional[Sequence[Optional[float]]] = None,
    min_edge: float = 0.02,
    flat_stake: float = 1.0,
) -> Dict[str, Any]:
    """ROI simulé : mise à plat quand proba modèle > implied + min_edge.

    Si odds_implied absent, utilise une cote fixe 2.0 (proxy neutre).
    """
    bets = wins = 0
    pnl = 0.0
    for i, (yt, prob) in enumerate(zip(y_true, y_proba)):
        implied = None
        if odds_implied is not None and i < len(odds_implied):
            implied = odds_implied[i]
        market_p = implied if implied is not None else 0.5
        edge = prob - market_p
        if edge < min_edge:
            continue
        bets += 1
        # Cote décimale approximée depuis implied prob
        dec_odds = (1.0 / market_p) if market_p > 0 else 2.0
        if int(yt) == 1:
            wins += 1
            pnl += flat_stake * (dec_odds - 1.0)
        else:
            pnl -= flat_stake
    roi_pct = (pnl / (bets * flat_stake) * 100.0) if bets else None
    return {
        "n_bets": bets,
        "n_wins": wins,
        "hit_rate": round(wins / bets, 4) if bets else None,
        "pnl_units": round(pnl, 4),
        "roi_pct": round(roi_pct, 2) if roi_pct is not None else None,
        "min_edge": min_edge,
        "note": "Simulation indicative — pas de déploiement production.",
    }


def evaluate_holdout(
    y_true: Sequence[int],
    y_pred: Sequence[int],
    y_proba: Sequence[float],
    odds_implied: Optional[Sequence[Optional[float]]] = None,
) -> Dict[str, Any]:
    """Métriques consolidées sur le hold-out."""
    acc = accuracy(y_true, y_pred)
    auc = auc_score(y_true, y_proba)
    roi = simulate_roi(y_true, y_proba, odds_implied)
    brier = None
    if y_true:
        brier = sum((float(p) - int(t)) ** 2 for t, p in zip(y_true, y_proba)) / len(y_true)
    return {
        "accuracy": round(acc, 4) if not math.isnan(acc) else None,
        "auc": round(auc, 4) if auc is not None else None,
        "brier": round(brier, 4) if brier is not None else None,
        "roi_simulation": roi,
        "n": len(y_true),
    }
