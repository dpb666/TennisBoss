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


# Poids modèle par défaut tant que fit_market_blend n'a pas appris (modèle
# faible vs marché -> prior prudent, surtout du marché).
DEFAULT_MARKET_BLEND_W = 0.2


def blend_probs(p_model: float, p_market: float, w: float) -> float:
    """Mélange modèle/marché en logit : sigmoid(w·logit(modèle) + (1−w)·logit(marché)).

    w=0 -> marché pur ; w=1 -> modèle pur. Le marché sert de prior, le modèle
    n'écarte la proba que proportionnellement à son poids appris.
    """
    w = _clamp(w, 0.0, 1.0)
    return _sigmoid(w * _logit(p_model) + (1.0 - w) * _logit(p_market))


def fit_market_blend(samples: List[Tuple[float, float, float]],
                     min_n: int = 30) -> Dict[str, Any]:
    """Cherche le poids modèle w qui minimise la log-loss du blend modèle/marché.

    `samples` : (p_modèle_calibrée, p_marché, issue 0/1), probas dans (0,1).
    Grille w ∈ [0, 1] pas 0.05. Rapporte aussi la log-loss marché pur (w=0)
    et modèle pur (w=1) pour juger si le modèle apporte quelque chose.
    """
    if len(samples) < min_n:
        return {"market_blend_w": None, "n": len(samples), "fitted": False,
                "note": f"Pas assez de paris réglés pour régler w (min {min_n})."}

    def ll(w: float) -> float:
        tot = 0.0
        for pm, pk, y in samples:
            p = _clamp(blend_probs(pm, pk, w), _EPS, 1 - _EPS)
            tot += -(y * math.log(p) + (1 - y) * math.log(1 - p))
        return tot / len(samples)

    grid = [i / 20.0 for i in range(0, 21)]   # 0.00 .. 1.00
    best = min(grid, key=ll)
    return {
        "market_blend_w": round(best, 2),
        "n": len(samples),
        "fitted": True,
        "logloss_market": round(ll(0.0), 4),
        "logloss_model": round(ll(1.0), 4),
        "logloss_best": round(ll(best), 4),
        "interpretation": ("le modèle n'apporte rien (marché pur)" if best == 0.0 else
                           "modèle dominant" if best >= 0.5 else
                           "le modèle ajuste le marché à la marge"),
    }


def tune_blend(samples: List[Tuple[float, float, float]],
               min_n: int = 20) -> Dict[str, Any]:
    """Cherche le poids ELO β qui minimise la log-loss.

    `samples` : (logit_features, logit_elo_brut, issue 0/1). On teste une grille
    β ∈ [0, 2] et on garde le meilleur. β=0 -> ELO ignoré ; β grand -> ELO dominant.
    """
    if len(samples) < min_n:
        return {"elo_blend": None, "n": len(samples), "fitted": False,
                "note": f"Pas assez de données pour régler β (min {min_n})."}

    def ll(beta: float) -> float:
        tot = 0.0
        for fl, el, y in samples:
            p = _clamp(_sigmoid(fl + beta * el), _EPS, 1 - _EPS)
            tot += -(y * math.log(p) + (1 - y) * math.log(1 - p))
        return tot / len(samples)

    grid = [i / 10.0 for i in range(0, 31)]   # 0.0 .. 3.0
    best = min(grid, key=ll)
    return {"elo_blend": round(best, 2), "n": len(samples), "fitted": True,
            "logloss_no_elo": round(ll(0.0), 4), "logloss_best": round(ll(best), 4)}


def _logloss(data: List[Tuple[float, float]], k: float) -> float:
    tot = 0.0
    for z, y in data:
        p = _clamp(_sigmoid(k * z), _EPS, 1 - _EPS)
        tot += -(y * math.log(p) + (1 - y) * math.log(1 - p))
    return tot / len(data)


def calibrated_prob_platt(p: float, a: float, b: float) -> float:
    """Platt scaling : sigmoid(a · logit(p) + b).

    a=1, b=0 → identité. a<1 → sur-confiance compressée. b≠0 → biais systématique.
    """
    return _sigmoid(a * _logit(p) + b)


def fit_platt(rows: List[Any], iters: int = 1000, lr: float = 0.05,
              min_n: int = 30) -> Dict[str, Any]:
    """Ajuste (a, b) par descente de gradient (log-loss) sur les matchs réglés.

    p_calibré = sigmoid(a · logit(pred_prob1) + b)
    pred_prob1 est en %, issue = 1 si winner == player1.
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
        return {"a": 1.0, "b": 0.0, "n": len(data), "fitted": False,
                "note": f"Pas assez de données (min {min_n})."}

    # Adam optimizer pour convergence stable
    a, b = 1.0, 0.0
    m_a = m_b = v_a = v_b = 0.0
    beta1, beta2, eps_adam = 0.9, 0.999, 1e-8

    def logloss(a_: float, b_: float) -> float:
        tot = sum(
            -(y * math.log(_clamp(_sigmoid(a_ * z + b_), _EPS, 1 - _EPS))
              + (1 - y) * math.log(_clamp(1 - _sigmoid(a_ * z + b_), _EPS, 1 - _EPS)))
            for z, y in data
        )
        return tot / len(data)

    for t in range(1, iters + 1):
        g_a = g_b = 0.0
        for z, y in data:
            p_hat = _clamp(_sigmoid(a * z + b), _EPS, 1 - _EPS)
            err = p_hat - y
            g_a += err * z
            g_b += err
        g_a /= len(data)
        g_b /= len(data)

        # Adam
        m_a = beta1 * m_a + (1 - beta1) * g_a
        m_b = beta1 * m_b + (1 - beta1) * g_b
        v_a = beta2 * v_a + (1 - beta2) * g_a ** 2
        v_b = beta2 * v_b + (1 - beta2) * g_b ** 2
        m_a_h = m_a / (1 - beta1 ** t)
        m_b_h = m_b / (1 - beta1 ** t)
        v_a_h = v_a / (1 - beta2 ** t)
        v_b_h = v_b / (1 - beta2 ** t)
        a = _clamp(a - lr * m_a_h / (v_a_h ** 0.5 + eps_adam), 0.05, 5.0)
        b = _clamp(b - lr * m_b_h / (v_b_h ** 0.5 + eps_adam), -3.0, 3.0)

    ll_before = logloss(1.0, 0.0)
    ll_after  = logloss(a, b)
    return {
        "a": round(a, 4),
        "b": round(b, 4),
        "n": len(data),
        "fitted": True,
        "logloss_before": round(ll_before, 4),
        "logloss_after":  round(ll_after,  4),
        "gain_pct": round((ll_before - ll_after) / ll_before * 100, 2),
        "interpretation": (
            f"slope={a:.3f} (sur-confiant)" if a < 0.8 else
            f"slope={a:.3f} (légère surconf.)" if a < 0.95 else
            f"slope={a:.3f} (bien calibré)"
        ),
    }


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
