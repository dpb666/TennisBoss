"""Système ELO pour le tennis — meilleur prédicteur simple à partir des seuls
résultats (vainqueur/perdant). Sert de signal fort en plus des features.

ELO : chaque joueur a une note ; on met à jour après chaque match selon la
surprise du résultat. La probabilité que A batte B :
    P(A) = 1 / (1 + 10^((eloB - eloA)/400))
"""
from __future__ import annotations

import math
from typing import Any, Dict, Iterable

BASE = 1500.0
K = 24.0


def expected(ra: float, rb: float) -> float:
    """Probabilité (match) que A batte B selon l'ELO."""
    return 1.0 / (1.0 + 10 ** ((rb - ra) / 400.0))


def match_logit(ra: float, rb: float) -> float:
    """Logit ELO (pour A) = ln(P/(1-P)). Sert à mélanger avec le modèle."""
    return (ra - rb) / 400.0 * math.log(10)


def update(ratings: Dict[str, float], winner: str, loser: str,
           base: float = BASE, k: float = K) -> Dict[str, float]:
    """Met à jour les notes ELO après UN match (winner bat loser)."""
    if not winner or not loser:
        return ratings
    rw = ratings.get(winner, base)
    rl = ratings.get(loser, base)
    ew = expected(rw, rl)
    ratings[winner] = rw + k * (1.0 - ew)
    ratings[loser] = rl + k * (0.0 - (1.0 - ew))
    return ratings


def build_from_matches(rows: Iterable[Any], base: float = BASE,
                       k: float = K) -> Dict[str, float]:
    """Construit les notes ELO à partir de matchs CHRONOLOGIQUES (date croissante).

    `rows` : objets avec ['winner'] et ['loser'] (noms).
    """
    ratings: Dict[str, float] = {}
    for r in rows:
        update(ratings, r["winner"], r["loser"], base, k)
    return ratings
