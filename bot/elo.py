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

# K-factor dynamique : forte incertitude pour les nouveaux joueurs, stable pour les établis.
K_FAST = 64.0   # < N_FAST matchs   (joueur inconnu, converge vite)
K_STD  = 28.0   # N_FAST..N_SLOW    (standard)
K_SLOW = 12.0   # > N_SLOW matchs   (établi, résistant aux coups isolés)
N_FAST = 30
N_SLOW = 150


def dynamic_k(n: int) -> float:
    """K-factor selon le nombre de matchs joués par le joueur."""
    if n < N_FAST:
        return K_FAST
    if n < N_SLOW:
        return K_STD
    return K_SLOW


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
    K fixe : pour les mises à jour live (settled_matches, matchs individuels).
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


def update_dynamic(ratings: Dict[str, float], n_played: Dict[str, int],
                   winner: str, loser: str,
                   base: float = BASE, mult: float = 1.0) -> None:
    """Mise à jour ELO avec K-factor dynamique (dépend du nb de matchs joués).

    Non-zero-sum : chaque joueur utilise son propre K (comme FIDE).
    Met à jour `ratings` et `n_played` en place.
    """
    if not winner or not loser:
        return
    rw = ratings.get(winner, base)
    rl = ratings.get(loser, base)
    ew = expected(rw, rl)
    kw = dynamic_k(n_played.get(winner, 0))
    kl = dynamic_k(n_played.get(loser, 0))
    # Delta = K * (score_réel - score_attendu) ; winner:1, loser:0
    # winner gagne kw*(1-ew), loser perd kl*(1-ew) [non-zero-sum si kw≠kl]
    ratings[winner] = rw + kw * mult * (1.0 - ew)
    ratings[loser]  = rl - kl * mult * (1.0 - ew)
    n_played[winner] = n_played.get(winner, 0) + 1
    n_played[loser]  = n_played.get(loser,  0) + 1


def build_from_matches(rows: Iterable[Any], base: float = BASE,
                       k: float = K) -> Dict[str, float]:
    """Construit les notes ELO à partir de matchs CHRONOLOGIQUES (date croissante).

    `rows` : objets avec ['winner'] et ['loser'] (noms).
    Utilise un K fixe — préférer build_dynamic() pour le K dynamique.
    """
    ratings: Dict[str, float] = {}
    for r in rows:
        update(ratings, r["winner"], r["loser"], base, k)
    return ratings


def build_dynamic(rows: Iterable[Any], base: float = BASE,
                  surface_key: str = None,
                  time_decay_days: int = 0) -> tuple:
    """Construit ELO avec K dynamique + dominance (mult_from_margin).

    Renvoie (ratings, n_played).
    `surface_key` : si fourni, ne traite que les matchs de cette surface.
    `time_decay_days` : si > 0, pondère les matchs par exp(-decay*(age_jours/time_decay_days)).
                        Recommandé : 365 (matchs de plus d'un an comptent ~37% moins).
    """
    import datetime as _dt
    ratings: Dict[str, float] = {}
    n_played: Dict[str, int] = {}
    today = _dt.date.today()

    for r in rows:
        surf = (r["surface"] or "").lower()
        if surface_key and surf != surface_key:
            continue
        try:
            m = r["margin"]
        except (KeyError, TypeError):
            m = None
        mult = mult_from_margin(m) if m is not None else 1.0

        # Décroissance temporelle : les matchs récents pèsent plus
        if time_decay_days > 0:
            try:
                match_date = _dt.date.fromisoformat(str(r["date"])[:10])
                age_days = (today - match_date).days
                if age_days > 0:
                    import math
                    decay = math.exp(-age_days / time_decay_days)
                    mult *= max(decay, 0.3)  # plancher à 30% du poids nominal
            except Exception:
                pass

        update_dynamic(ratings, n_played, r["winner"], r["loser"], base, mult)
    return ratings, n_played


def build_recent(rows: Iterable[Any], base: float = BASE,
                 days: int = 180, surface_key: str = None) -> tuple:
    """ELO de forme récente — uniquement les matchs des derniers `days` jours.

    Retourne (ratings, n_played). Utile comme signal de forme courte.
    """
    import datetime as _dt
    cutoff = (_dt.date.today() - _dt.timedelta(days=days)).isoformat()
    recent = [r for r in rows if str(r["date"] if "date" in r.keys() else "")[:10] >= cutoff]
    return build_dynamic(recent, base, surface_key=surface_key)
