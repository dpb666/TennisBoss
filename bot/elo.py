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


def mult_from_margin(margin: float) -> float:
    """Multiplicateur de marge de victoire (en jeux), borné [0.7, 1.6]."""
    return max(0.7, min(1.6, 0.5 + 0.4 * math.log(max(0, margin) + 1)))


def dominance_mult(sets: Any, winner_side: str = "p1") -> float:
    """Multiplicateur de marge d'après les scores set-par-set du vainqueur.

    Un 6-1 6-2 (grosse marge en jeux) pèse plus qu'un 7-6 7-6 (marge faible).
    `sets` : [{"first": jeux J1, "second": jeux J2}, ...].
    """
    wg = lg = 0
    for s in (sets or []):
        try:
            f = int(s.get("first"))
            g = int(s.get("second"))
        except (TypeError, ValueError):
            continue
        if winner_side == "p1":
            wg += f
            lg += g
        else:
            wg += g
            lg += f
    return mult_from_margin(wg - lg)


def update(ratings: Dict[str, float], winner: str, loser: str,
           base: float = BASE, k: float = K, mult: float = 1.0) -> Dict[str, float]:
    """Met à jour les notes ELO après UN match (winner bat loser).

    `mult` : multiplicateur de marge de victoire (cf. dominance_mult).
    """
    if not winner or not loser:
        return ratings
    rw = ratings.get(winner, base)
    rl = ratings.get(loser, base)
    ew = expected(rw, rl)
    delta = k * mult * (1.0 - ew)
    ratings[winner] = rw + delta
    ratings[loser] = rl - delta
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
