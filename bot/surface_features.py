"""Surface-specific features for offline experiments (ROI MODE).

Each function documents its math definition in the docstring. Features are
oriented player1 − player2 (positive favours player1). Designed for walk-forward
evaluation — never use future match data when computing features at time t.
"""
from __future__ import annotations

import datetime as _dt
import math
from collections import defaultdict
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from bot import elo as elo_mod

_SURFACES = frozenset({"hard", "clay", "grass"})
_DEFAULT_ALPHA = 0.15


def _norm_surface(surface: Optional[str]) -> str:
    return (surface or "").strip().lower()


def _norm_date(date_str: str) -> str:
    return str(date_str or "").replace("-", "")[:8]


def _parse_date(date_str: str) -> Optional[_dt.date]:
    compact = _norm_date(date_str)
    if len(compact) != 8 or not compact.isdigit():
        return None
    try:
        return _dt.date(int(compact[:4]), int(compact[4:6]), int(compact[6:8]))
    except ValueError:
        return None


def _days_between(d1: str, d2: str) -> Optional[int]:
    a, b = _parse_date(d1), _parse_date(d2)
    if a is None or b is None:
        return None
    return abs((b - a).days)


class MatchHistoryIndex:
    """In-memory index of past matches for fast surface feature lookups.

    Build once from matches strictly BEFORE the evaluation window to avoid
    leakage. Each row needs: winner_name, loser_name, date, surface.
    """

    def __init__(self, matches: Sequence[Mapping[str, Any]]) -> None:
        self._by_player: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        ordered = sorted(
            matches,
            key=lambda m: (_norm_date(str(m.get("date") or "")), str(m.get("id") or "")),
        )
        for m in ordered:
            w = m.get("winner_name") or m.get("winner")
            l = m.get("loser_name") or m.get("loser")
            if not w or not l:
                continue
            row = {
                "date": str(m.get("date") or ""),
                "date_compact": _norm_date(str(m.get("date") or "")),
                "surface": _norm_surface(m.get("surface")),
                "won": True,
                "opponent": l,
            }
            self._by_player[w].append(row)
            self._by_player[l].append({
                **row,
                "won": False,
                "opponent": w,
            })

    def add_match(self, match: Mapping[str, Any]) -> None:
        """Append one match to the index (walk-forward update)."""
        w = match.get("winner_name") or match.get("winner")
        l = match.get("loser_name") or match.get("loser")
        if not w or not l:
            return
        surf = _norm_surface(match.get("surface"))
        row = {
            "date": str(match.get("date") or ""),
            "date_compact": _norm_date(str(match.get("date") or "")),
            "surface": surf,
            "won": True,
            "opponent": l,
        }
        self._by_player[w].append(row)
        self._by_player[l].append({**row, "won": False, "opponent": w})

    def player_matches(
        self,
        player: str,
        before_date: Optional[str] = None,
        surface: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """Matches for `player` before `before_date`, optionally filtered by surface."""
        cutoff = _norm_date(before_date) if before_date else None
        surf = _norm_surface(surface) if surface else None
        rows = self._by_player.get(player, [])
        out: List[Dict[str, Any]] = []
        for r in reversed(rows):
            if cutoff and r["date_compact"] >= cutoff:
                continue
            if surf and r["surface"] != surf:
                continue
            out.append(r)
            if limit and len(out) >= limit:
                break
        return out


def win_rate_surface(
    player: str,
    surface: str,
    history: MatchHistoryIndex,
    before_date: str,
    n: int = 10,
) -> Optional[float]:
    """Win rate on `surface` over the last `n` matches on that surface.

    Math: WR = wins / min(n, available_matches_on_surface)
    Unit: probability in [0, 1]. Returns None if no matches on surface.
    """
    surf = _norm_surface(surface)
    if surf not in _SURFACES:
        return None
    rows = history.player_matches(player, before_date=before_date, surface=surf, limit=n)
    if not rows:
        return None
    wins = sum(1 for r in rows if r["won"])
    return wins / len(rows)


def weighted_recent_form_surface(
    player: str,
    surface: str,
    history: MatchHistoryIndex,
    before_date: str,
    n: int = 10,
    alpha: float = _DEFAULT_ALPHA,
) -> Optional[float]:
    """EMA of match outcomes (1=win, 0=loss) on `surface`, most recent first.

    Math: F_0 = outcome_0 ; F_t = (1-α)·F_{t-1} + α·outcome_t
    Unit: probability in [0, 1]. Returns None if no surface history.
    """
    surf = _norm_surface(surface)
    if surf not in _SURFACES:
        return None
    rows = history.player_matches(player, before_date=before_date, surface=surf, limit=n)
    if not rows:
        return None
    form = 0.5
    for r in rows:
        outcome = 1.0 if r["won"] else 0.0
        form = (1.0 - alpha) * form + alpha * outcome
    return form


def surface_elo_diff(
    p1: str,
    p2: str,
    surface: str,
    elo_surface: Mapping[str, Mapping[str, float]],
    elo_global: Optional[Mapping[str, float]] = None,
) -> Optional[float]:
    """Difference of surface Elo ratings, normalised to logit scale.

    Math: (Elo_surf(p1) - Elo_surf(p2)) / 400
    Falls back to global Elo when player missing from surface map.
    Unit: dimensionless (same scale as ml_prep surface_elo_diff).
    """
    surf = _norm_surface(surface)
    if surf not in _SURFACES:
        return None
    global_map = elo_global or {}
    surf_map = elo_surface.get(surf) or {}
    r1 = surf_map.get(p1, global_map.get(p1, elo_mod.BASE))
    r2 = surf_map.get(p2, global_map.get(p2, elo_mod.BASE))
    return (r1 - r2) / 400.0


def surface_momentum(
    player: str,
    surface: str,
    history: MatchHistoryIndex,
    before_date: str,
    recent_n: int = 5,
    baseline_n: int = 20,
) -> Optional[float]:
    """Recent surface win rate minus longer-term surface win rate.

    Math: WR(last `recent_n` on surface) - WR(last `baseline_n` on surface)
    Unit: probability delta in [-1, 1]. Positive = improving form on surface.
    """
    surf = _norm_surface(surface)
    if surf not in _SURFACES:
        return None
    rows = history.player_matches(player, before_date=before_date, surface=surf, limit=baseline_n)
    if len(rows) < 2:
        return None
    recent = rows[:recent_n]
    wins_recent = sum(1 for r in recent if r["won"]) / len(recent)
    wins_base = sum(1 for r in rows if r["won"]) / len(rows)
    return wins_recent - wins_base


def fatigue_on_surface(
    player: str,
    surface: str,
    history: MatchHistoryIndex,
    before_date: str,
) -> Optional[float]:
    """Days since the player's last match on the same surface.

    Math: days_between(last_surface_match_date, before_date)
    Unit: days (non-negative integer as float). None if no prior surface match.
    Lower values indicate less rest (more fatigue risk).
    """
    surf = _norm_surface(surface)
    if surf not in _SURFACES:
        return None
    rows = history.player_matches(player, before_date=before_date, surface=surf, limit=1)
    if not rows:
        return None
    days = _days_between(rows[0]["date"], before_date)
    return float(days) if days is not None else None


def tournament_surface_experience(
    player: str,
    surface: str,
    history: MatchHistoryIndex,
    before_date: str,
) -> int:
    """Count of archived matches played on `surface` before `before_date`.

    Math: |{matches : player ∈ {winner,loser}, surface = s, date < before_date}|
    Unit: match count (integer ≥ 0).
    """
    surf = _norm_surface(surface)
    if surf not in _SURFACES:
        return 0
    return len(history.player_matches(player, before_date=before_date, surface=surf))


def surface_feature_diffs(
    p1: str,
    p2: str,
    surface: str,
    history: MatchHistoryIndex,
    before_date: str,
    elo_surface: Optional[Mapping[str, Mapping[str, float]]] = None,
    elo_global: Optional[Mapping[str, float]] = None,
    *,
    include_elo: bool = False,
) -> Dict[str, Optional[float]]:
    """All surface feature differences (p1 − p2) for one matchup."""
    out: Dict[str, Optional[float]] = {
        "win_rate_surface_diff": _safe_diff(
            win_rate_surface(p1, surface, history, before_date, n=10),
            win_rate_surface(p2, surface, history, before_date, n=10),
        ),
        "win_rate_surface_20_diff": _safe_diff(
            win_rate_surface(p1, surface, history, before_date, n=20),
            win_rate_surface(p2, surface, history, before_date, n=20),
        ),
        "weighted_form_surface_diff": _safe_diff(
            weighted_recent_form_surface(p1, surface, history, before_date),
            weighted_recent_form_surface(p2, surface, history, before_date),
        ),
        "surface_momentum_diff": _safe_diff(
            surface_momentum(p1, surface, history, before_date),
            surface_momentum(p2, surface, history, before_date),
        ),
        "fatigue_on_surface_diff": _safe_diff(
            fatigue_on_surface(p2, surface, history, before_date),
            fatigue_on_surface(p1, surface, history, before_date),
        ),
        "tournament_surface_exp_diff": float(
            tournament_surface_experience(p1, surface, history, before_date)
            - tournament_surface_experience(p2, surface, history, before_date)
        ),
    }
    if include_elo and elo_surface is not None:
        out["surface_elo_diff"] = surface_elo_diff(
            p1, p2, surface, elo_surface, elo_global,
        )
    return out


def _safe_diff(a: Optional[float], b: Optional[float]) -> Optional[float]:
    if a is None or b is None:
        return None
    return float(a) - float(b)


def impute_diffs(diffs: Mapping[str, Optional[float]], fill: float = 0.0) -> Dict[str, float]:
    """Replace None with `fill` for model input."""
    return {k: fill if v is None else float(v) for k, v in diffs.items()}


def surface_logit_from_diffs(
    diffs: Mapping[str, Optional[float]],
    weights: Mapping[str, float],
    fill: float = 0.0,
) -> float:
    """Linear combination of surface feature diffs added to baseline logit."""
    total = 0.0
    for name, w in weights.items():
        val = diffs.get(name)
        if val is None:
            val = fill
        total += float(w) * float(val)
    return total


def fit_surface_weights(
    rows: Sequence[Tuple[Dict[str, Optional[float]], float]],
    feature_names: Sequence[str],
    *,
    iters: int = 400,
    lr: float = 0.05,
    l2: float = 0.01,
) -> Dict[str, float]:
    """Fit logistic weights on (feature_diffs, y) minimizing log-loss.

    `y` = 1 if player1 (alphabetically first) won. Returns weight per feature.
    """
    weights = {name: 0.0 for name in feature_names}
    if not rows:
        return weights

    def sigmoid(z: float) -> float:
        if z < -60:
            return 0.0
        if z > 60:
            return 1.0
        return 1.0 / (1.0 + math.exp(-z))

    eps = 1e-9
    for _ in range(iters):
        grads = {name: 0.0 for name in feature_names}
        for diffs, y in rows:
            z = surface_logit_from_diffs(diffs, weights)
            p = sigmoid(z)
            err = p - y
            for name in feature_names:
                val = diffs.get(name)
                if val is None:
                    val = 0.0
                grads[name] += err * float(val)
        n = len(rows)
        for name in feature_names:
            weights[name] -= lr * (grads[name] / n + l2 * weights[name])
    return {k: round(v, 4) for k, v in weights.items()}


SURFACE_FEATURE_NAMES: Tuple[str, ...] = (
    "win_rate_surface_diff",
    "win_rate_surface_20_diff",
    "weighted_form_surface_diff",
    "surface_momentum_diff",
    "fatigue_on_surface_diff",
    "tournament_surface_exp_diff",
)
