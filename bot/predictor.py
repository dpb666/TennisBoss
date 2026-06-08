"""Modèle de prédiction du 1er set.

On garde l'esprit de votre script (score pondéré serve/return1/return2/recent)
mais on le rend apprenant : la probabilité est calculée par une régression
logistique sur la DIFFÉRENCE des features entre les deux joueurs.

    score_i = Σ_k  poids_k * feature_i_k
    z       = (score1 - score2) + biais
    P(J1)   = sigmoid(z)
"""
from __future__ import annotations

import math
from typing import Any, Dict, Tuple

from . import config


def set_to_match_prob(p_set: float) -> float:
    """Proba de gagner UN set -> proba de gagner le MATCH (best-of-3).

    Sets supposés indépendants de proba p :  P(match) = p²·(3 - 2p).
    """
    p = max(0.0, min(1.0, p_set))
    return p * p * (3 - 2 * p)


def _sigmoid(z: float) -> float:
    if z < -60:
        return 0.0
    if z > 60:
        return 1.0
    return 1.0 / (1.0 + math.exp(-z))


def weighted_score(weights: Dict[str, float], feat: Dict[str, float]) -> float:
    return sum(weights.get(k, 0.0) * feat.get(k, 0.0) for k in config.FEATURE_ORDER)


def probability(
    weights: Dict[str, float],
    bias: float,
    feat1: Dict[str, float],
    feat2: Dict[str, float],
) -> Tuple[float, float, float, float]:
    """Renvoie (proba_J1, proba_J2, score1, score2)."""
    score1 = weighted_score(weights, feat1)
    score2 = weighted_score(weights, feat2)
    z = (score1 - score2) + bias
    p1 = _sigmoid(z)
    return p1, 1.0 - p1, score1, score2


# Poids du signal ELO mélangé au modèle (l'ELO bat le modèle seul out-of-sample).
ELO_BLEND = 0.8
ELO_BASE = 1500.0


def elo_logit(mem: Dict[str, Any], name1: str, name2: str) -> float:
    """Contribution ELO (déjà pondérée) au logit de la prédiction.

    Le poids de mélange est `mem['elo_blend']` s'il existe (auto-réglé), sinon
    ELO_BLEND par défaut."""
    elo = mem.get("elo") or {}
    if not elo:
        return 0.0
    blend = float(mem.get("elo_blend", ELO_BLEND))
    ra = elo.get(name1, ELO_BASE)
    rb = elo.get(name2, ELO_BASE)
    return blend * ((ra - rb) / 400.0 * math.log(10))


def predict(
    mem: Dict[str, Any],
    name1: str,
    feat1: Dict[str, float],
    name2: str,
    feat2: Dict[str, float],
) -> Dict[str, Any]:
    """Construit un résultat de prédiction lisible pour le 1er set (features + ELO)."""
    s1 = weighted_score(mem["weights"], feat1)
    s2 = weighted_score(mem["weights"], feat2)
    z = (s1 - s2) + float(mem["bias"]) + elo_logit(mem, name1, name2)
    p1 = _sigmoid(z)
    p2 = 1.0 - p1
    if abs(p1 - p2) < 0.04:
        verdict = "⚖️ Très serré — tie-break possible"
        favorite = None
    elif p1 > p2:
        verdict = f"🏆 {name1} favori pour gagner le 1er set"
        favorite = name1
    else:
        verdict = f"🏆 {name2} favori pour gagner le 1er set"
        favorite = name2
    return {
        "player1": name1,
        "player2": name2,
        "prob1": round(p1 * 100, 2),
        "prob2": round(p2 * 100, 2),
        "score1": round(s1, 4),
        "score2": round(s2, 4),
        "favorite": favorite,
        "verdict": verdict,
    }
