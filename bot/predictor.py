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


def _raw_logit(ratings: Dict[str, float], n1: str, n2: str) -> float:
    return (ratings.get(n1, ELO_BASE) - ratings.get(n2, ELO_BASE)) / 400.0 * math.log(10)


def elo_logit(mem: Dict[str, Any], name1: str, name2: str,
              surface: str = None) -> float:
    """Contribution ELO (déjà pondérée) au logit de la prédiction.

    Mélange 3 signaux ELO :
    - global (décroissance temporelle 365j)
    - surface (si disponible)
    - forme récente 180j (surpondère les joueurs chauds)
    Poids de mélange = mem['elo_blend'] (auto-réglé) sinon ELO_BLEND.
    """
    elo = mem.get("elo") or {}
    if not elo:
        return 0.0
    blend = float(mem.get("elo_blend", ELO_BLEND))
    base = _raw_logit(elo, name1, name2)

    surf_map = mem.get("elo_surface") or {}
    if surface and surface in surf_map:
        surf_logit = _raw_logit(surf_map[surface], name1, name2)
        combined = 0.45 * base + 0.45 * surf_logit
    else:
        combined = base

    # ELO récent (180j) — signal de forme courte
    elo_rec = mem.get("elo_recent") or {}
    if elo_rec and (name1 in elo_rec or name2 in elo_rec):
        rec_logit = _raw_logit(elo_rec, name1, name2)
        if surface and surface in surf_map:
            combined = 0.40 * base + 0.40 * surf_logit + 0.20 * rec_logit
        else:
            combined = 0.80 * base + 0.20 * rec_logit

    return blend * combined


_CONF_MIN_MATCHES = 30


def confidence_score(mem: Dict[str, Any], name1: str, name2: str, z: float) -> float:
    """Score de confiance [0..1] de la prédiction.

    Combine deux signaux :
    - data_conf  : fiabilité des profils (sature à _CONF_MIN_MATCHES matchs chacun)
    - margin_conf: amplitude du logit z (|z|=2 => très tranché)
    """
    players = mem.get("players") or {}
    n1 = int(players.get(name1, {}).get("n", 0))
    n2 = int(players.get(name2, {}).get("n", 0))
    data_conf = min(min(n1, n2), _CONF_MIN_MATCHES) / _CONF_MIN_MATCHES
    margin_conf = min(abs(z) * 0.5, 1.0)
    return round(0.6 * data_conf + 0.4 * margin_conf, 2)


def confidence_label(score: float) -> str:
    if score < 0.40:
        return "faible"
    if score < 0.65:
        return "modérée"
    if score < 0.80:
        return "bonne"
    return "élevée"


def predict(
    mem: Dict[str, Any],
    name1: str,
    feat1: Dict[str, float],
    name2: str,
    feat2: Dict[str, float],
    surface: str = None,
) -> Dict[str, Any]:
    """Construit un résultat de prédiction lisible pour le 1er set (features + ELO).

    `surface` ('hard'/'clay'/'grass') active l'ELO de surface si connu."""
    s1 = weighted_score(mem["weights"], feat1)
    s2 = weighted_score(mem["weights"], feat2)
    z = (s1 - s2) + float(mem["bias"]) + elo_logit(mem, name1, name2, surface)
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
    conf = confidence_score(mem, name1, name2, z)
    return {
        "player1": name1,
        "player2": name2,
        "prob1": round(p1 * 100, 2),
        "prob2": round(p2 * 100, 2),
        "score1": round(s1, 4),
        "score2": round(s2, 4),
        "favorite": favorite,
        "verdict": verdict,
        "surface": surface,
        "confidence": conf,
        "confidence_label": confidence_label(conf),
    }
