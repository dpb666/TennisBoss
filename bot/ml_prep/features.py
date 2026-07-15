"""Features ML pour la prédiction match (hors-ligne).

Colonnes : ranking diff, ELO diff, ELO surface, forme, serve/return, mouvement
de cotes. Chaque feature est orientée player1 − player2 (player1 = nom le plus
petit en ordre alphabétique pour éviter un label dégénéré).
"""
from __future__ import annotations

import math
from collections import defaultdict
from typing import Any, Dict, List, Mapping, Optional, Tuple

from bot import config, elo as elo_mod, features as player_features

FEATURE_NAMES: List[str] = [
    "ranking_diff",
    "elo_diff",
    "surface_elo_diff",
    "form_diff",
    "serve_diff",
    "return1_diff",
    "return2_diff",
    "odds_implied_p1",
    "odds_move_home_pct",
    "odds_move_away_pct",
]

_SURFACES = ("hard", "clay", "grass")


def orient_players(winner: str, loser: str) -> Tuple[str, str, int]:
    """player1 = min(alpha), player2 = max ; y = 1 si player1 a gagné."""
    p1, p2 = (winner, loser) if winner <= loser else (loser, winner)
    y = 1 if winner == p1 else 0
    return p1, p2, y


def _elo_fallback_ranks(mem: Mapping[str, Any]) -> Dict[str, float]:
    """Rang synthétique depuis Elo global (1=meilleur) pour joueurs sans classement officiel."""
    elo = (mem or {}).get("elo") or {}
    if not elo:
        return {}
    ordered = sorted(elo.items(), key=lambda kv: -float(kv[1]))
    return {name: float(i + 1) for i, (name, _) in enumerate(ordered)}


def load_rankings(mem: Optional[Mapping[str, Any]] = None) -> Dict[str, float]:
    """Charge les rankings depuis player_rankings (DB) puis memory.json.

    La table player_rankings (ranking_feeder) prime sur le ranking moyen
    historique en memory.json. Les joueurs sans classement officiel reçoivent
    un rang Elo synthétique (fallback) pour ranking_diff.
    """
    out: Dict[str, float] = {}
    try:
        from bot import db
        db.init()
        for name, rank in db.get_all_player_rankings().items():
            out[name] = float(rank)
    except Exception:
        pass
    if mem is None:
        try:
            from bot import memory
            mem = memory.load()
        except Exception:
            mem = {}
    players = (mem or {}).get("players") or {}
    for name, prof in players.items():
        if name in out:
            continue
        rank = prof.get("rank")
        if rank is not None:
            try:
                out[name] = float(rank)
            except (TypeError, ValueError):
                pass
    for name, rank in _elo_fallback_ranks(mem).items():
        if name not in out:
            out[name] = rank
    return out


def _safe_diff(a: Optional[float], b: Optional[float]) -> Optional[float]:
    if a is None or b is None:
        return None
    return float(a) - float(b)


def _implied_prob(odds: Optional[float]) -> Optional[float]:
    if odds is None or odds <= 1.0:
        return None
    return 1.0 / float(odds)


def odds_features_for_match(
    p1: str,
    p2: str,
    winner: str,
    date_key: str,
    odds_index: Mapping[tuple, Mapping[str, Any]],
    line_moves: Optional[Mapping[str, Mapping[str, Any]]] = None,
    event_key: Optional[str] = None,
) -> Dict[str, Optional[float]]:
    """Cotes historiques (tennis-data) + mouvement live (market_snapshots)."""
    out: Dict[str, Optional[float]] = {
        "odds_implied_p1": None,
        "odds_move_home_pct": None,
        "odds_move_away_pct": None,
    }
    key = (date_key, winner, p2 if winner == p1 else p1)
    # historical_odds indexe (date, winner, loser) — essayer les deux orientations
    row = odds_index.get(key)
    if row is None:
        alt = (date_key, p2, p1) if winner == p1 else (date_key, p1, p2)
        row = odds_index.get(alt)
    if row:
        # avgw/avgl = cotes du vainqueur/perdant dans l'index
        if winner == p1:
            odds_p1 = row.get("avgw") or row.get("psw")
        else:
            odds_p1 = row.get("avgl") or row.get("psl")
        out["odds_implied_p1"] = _implied_prob(odds_p1)

    if line_moves and event_key:
        mv = line_moves.get(event_key)
        if mv:
            out["odds_move_home_pct"] = mv.get("move_home_pct")
            out["odds_move_away_pct"] = mv.get("move_away_pct")
    return out


def profile_diffs(
    mem: Mapping[str, Any],
    p1: str,
    p2: str,
) -> Dict[str, Optional[float]]:
    """Différences serve / return / forme (EMA) avant le match."""
    prof1 = player_features.get_profile(mem, p1)
    prof2 = player_features.get_profile(mem, p2)
    return {
        "form_diff": _safe_diff(prof1.get("recent"), prof2.get("recent")),
        "serve_diff": _safe_diff(prof1.get("serve"), prof2.get("serve")),
        "return1_diff": _safe_diff(prof1.get("return1"), prof2.get("return1")),
        "return2_diff": _safe_diff(prof1.get("return2"), prof2.get("return2")),
    }


def elo_diffs(
    p1: str,
    p2: str,
    surface: str,
    elo_ratings: Mapping[str, float],
    elo_surface: Mapping[str, Mapping[str, float]],
    rankings: Mapping[str, float],
) -> Dict[str, Optional[float]]:
    """ELO global, ELO surface, ranking (meilleur = nombre plus petit)."""
    r1 = elo_ratings.get(p1, elo_mod.BASE)
    r2 = elo_ratings.get(p2, elo_mod.BASE)
    surf = (surface or "").lower()
    surf_map = elo_surface.get(surf) or {}
    s1 = surf_map.get(p1, r1)
    s2 = surf_map.get(p2, r2)
    rank1 = rankings.get(p1)
    rank2 = rankings.get(p2)
    # ranking_diff positif = p1 mieux classé (rang plus bas)
    ranking_diff = _safe_diff(rank2, rank1) if rank1 is not None and rank2 is not None else None
    return {
        "ranking_diff": ranking_diff,
        "elo_diff": (r1 - r2) / 400.0,
        "surface_elo_diff": (s1 - s2) / 400.0,
    }


def build_feature_row(
    match: Mapping[str, Any],
    mem: Mapping[str, Any],
    elo_ratings: Mapping[str, float],
    elo_surface: Mapping[str, Mapping[str, float]],
    rankings: Mapping[str, float],
    odds_index: Mapping[tuple, Mapping[str, Any]],
    line_moves: Optional[Mapping[str, Mapping[str, Any]]] = None,
    event_key: Optional[str] = None,
) -> Dict[str, Any]:
    """Une ligne de features + métadonnées pour un match (état AVANT le match)."""
    winner = match["winner_name"]
    loser = match["loser_name"]
    p1, p2, y = orient_players(winner, loser)
    date_raw = str(match.get("date") or "")
    date_key = date_raw.replace("-", "")

    row: Dict[str, Any] = {
        "date": date_raw,
        "player1": p1,
        "player2": p2,
        "winner": winner,
        "surface": (match.get("surface") or "").lower(),
        "y": y,
    }
    row.update(elo_diffs(p1, p2, row["surface"], elo_ratings, elo_surface, rankings))
    row.update(profile_diffs(mem, p1, p2))
    row.update(
        odds_features_for_match(
            p1, p2, winner, date_key, odds_index, line_moves, event_key,
        )
    )
    return row


def init_elo_state() -> Tuple[
    Dict[str, float],
    Dict[str, Dict[str, float]],
    Dict[str, int],
    Dict[str, Dict[str, int]],
]:
    """État ELO vide (mis à jour match après match, sans fuite)."""
    return {}, {s: {} for s in _SURFACES}, {}, {s: {} for s in _SURFACES}


def update_elo_state(
    match: Mapping[str, Any],
    elo_ratings: Dict[str, float],
    elo_surface: Dict[str, Dict[str, float]],
    elo_n: Dict[str, int],
    elo_surf_n: Dict[str, Dict[str, int]],
) -> None:
    """Met à jour l'ELO global et par surface après un match."""
    w, l = match["winner_name"], match["loser_name"]
    mult = elo_mod.mult_from_margin(match.get("margin") or 0)
    elo_mod.update_dynamic(elo_ratings, elo_n, w, l, mult=mult)
    surf = (match.get("surface") or "").lower()
    if surf in elo_surface:
        elo_mod.update_dynamic(elo_surface[surf], elo_surf_n[surf], w, l, mult=mult)


def update_profile_state(
    mem: Dict[str, Any],
    match: Mapping[str, Any],
    alpha: float,
) -> None:
    """Met à jour les profils joueurs (EMA, sans toucher aux poids du modèle)."""
    w_perf = match.get("winner") or {}
    l_perf = match.get("loser") or {}
    tour = match.get("tour")
    player_features.update_profile(
        mem, match["winner_name"], w_perf, True, alpha, tour,
    )
    player_features.update_profile(
        mem, match["loser_name"], l_perf, False, alpha, tour,
    )


def rows_to_matrix(
    rows: List[Dict[str, Any]],
    feature_names: Optional[List[str]] = None,
    fill_value: float = 0.5,
) -> Tuple[List[List[float]], List[int], List[str]]:
    """Convertit des lignes dict en X, y ; NaN remplacés par fill_value."""
    names = feature_names or FEATURE_NAMES
    X: List[List[float]] = []
    y: List[int] = []
    for row in rows:
        vec = []
        for name in names:
            val = row.get(name)
            if val is None or (isinstance(val, float) and math.isnan(val)):
                vec.append(fill_value)
            else:
                vec.append(float(val))
        X.append(vec)
        y.append(int(row["y"]))
    return X, y, names
