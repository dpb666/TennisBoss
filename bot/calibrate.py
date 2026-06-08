"""Auto-calibration des probabilités du modèle (temperature scaling).

On n'a pas les features des matchs live, mais on a des paires
(probabilité prédite, issue réelle) dans `settled_matches`. On apprend un
facteur scalaire k tel que :

    p_calibré = sigmoid(k · logit(p))

- k = 1  : inchangé
- k < 1  : modèle sur-confiant -> on rapproche de 50 %
- k > 1  : modèle sous-confiant -> on accentue

k minimise la log-loss sur les matchs réglés. C'est de la calibration honnête :
on ne change pas QUI est favori, seulement le niveau de confiance.
"""
from __future__ import annotations

import math
from typing import Any, Dict, List, Tuple

_EPS = 1e-6


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def _logit(p: float) -> float:
    p = _clamp(p, _EPS, 1 - _EPS)
    return math.log(p / (1 - p))


def _sigmoid(z: float) -> float:
    if z < -60:
        return 0.0
    if z > 60:
        return 1.0
    return 1.0 / (1.0 + math.exp(-z))


def calibrated_prob(p: float, k: float) -> float:
    """Applique le facteur de calibration k à une probabilité p."""
    return _sigmoid(k * _logit(p))


def _logloss(data: List[Tuple[float, float]], k: float) -> float:
    tot = 0.0
    for z, y in data:
        p = _clamp(_sigmoid(k * z), _EPS, 1 - _EPS)
        tot += -(y * math.log(p) + (1 - y) * math.log(1 - p))
    return tot / len(data)


def fit_temperature(rows: List[Any], iters: int = 600, lr: float = 0.2,
                    min_n: int = 10) -> Dict[str, Any]:
    """Ajuste k sur les matchs réglés. `rows` : lignes settled_matches.

    pred_prob1 = proba (en %) que player1 gagne ; issue = 1 si winner == player1.
    """
    data: List[Tuple[float, float]] = []
    for r in rows:
        pp = r["pred_prob1"]
        if pp is None:
            continue
        z = _logit(pp / 100.0)
        y = 1.0 if r["winner"] == r["player1"] else 0.0
        data.append((z, y))

    if len(data) < min_n:
        return {"k": 1.0, "n": len(data), "fitted": False,
                "note": f"Pas assez de matchs réglés pour calibrer (min {min_n})."}

    k = 1.0
    for _ in range(iters):
        grad = sum((_sigmoid(k * z) - y) * z for z, y in data) / len(data)
        k = _clamp(k - lr * grad, 0.1, 3.0)

    return {
        "k": round(k, 3),
        "n": len(data),
        "fitted": True,
        "logloss_before": round(_logloss(data, 1.0), 4),
        "logloss_after": round(_logloss(data, k), 4),
        "interpretation": ("sur-confiant" if k < 0.95 else
                           "sous-confiant" if k > 1.05 else "bien calibré"),
    }
