"""Four probability models, each returning P(player1 wins first set).

- elo_probability       : dynamic-K ELO (global + surface blend)
- bayesian_adjustment   : market-informed posterior via log-odds blending
- feature_probability   : existing logistic regression from bot.predictor
- transformer_proxy     : surface-conditioned attention-style feature scoring
"""
from __future__ import annotations

import math
from typing import Any, Dict, Optional


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

_EPS = 1e-9


def _sigmoid(z: float) -> float:
    return 1.0 / (1.0 + math.exp(-max(-500.0, min(500.0, z))))


def _logit(p: float) -> float:
    p = max(_EPS, min(1.0 - _EPS, p))
    return math.log(p / (1.0 - p))


# ---------------------------------------------------------------------------
# 1. ELO probability
# ---------------------------------------------------------------------------

def elo_probability(
    mem: Dict[str, Any],
    name1: str,
    name2: str,
    surface: Optional[str] = None,
) -> float:
    """ELO-based P(player1 beats player2) — global + surface blend (50/50)."""
    BASE = 1500.0
    elo = mem.get("elo") or {}
    r1 = elo.get(name1, BASE)
    r2 = elo.get(name2, BASE)
    base_logit = (r1 - r2) / 400.0 * math.log(10)

    surf_map = mem.get("elo_surface") or {}
    if surface and surface in surf_map:
        sr = surf_map[surface]
        surf_logit = (sr.get(name1, BASE) - sr.get(name2, BASE)) / 400.0 * math.log(10)
        logit = 0.5 * base_logit + 0.5 * surf_logit
    else:
        logit = base_logit

    return _sigmoid(logit)


# ---------------------------------------------------------------------------
# 2. Bayesian market adjustment
# ---------------------------------------------------------------------------

def remove_vig(odds1: float, odds2: float) -> tuple[float, float]:
    """Convert bookmaker odds to fair probabilities (remove overround)."""
    raw1 = 1.0 / max(1.01, odds1)
    raw2 = 1.0 / max(1.01, odds2)
    total = raw1 + raw2
    return raw1 / total, raw2 / total


def bayesian_adjustment(
    model_prob: float,
    market_odds1: float,
    market_odds2: float,
    market_weight: float = 0.35,
) -> float:
    """Posterior = blend of model prior and market signal in log-odds space.

    Market encodes collective wisdom.  We trust it at `market_weight`
    and keep (1 - market_weight) from our model signal.
    """
    market_p1, _ = remove_vig(market_odds1, market_odds2)
    log_model  = _logit(model_prob)
    log_market = _logit(market_p1)
    posterior  = (1.0 - market_weight) * log_model + market_weight * log_market
    return _sigmoid(posterior)


# ---------------------------------------------------------------------------
# 3. Feature probability (existing logistic regression)
# ---------------------------------------------------------------------------

def feature_probability(
    mem: Dict[str, Any],
    name1: str,
    name2: str,
    surface: Optional[str] = None,
) -> float:
    """Logistic regression score from bot.features + bot.predictor."""
    from bot import features as feat_mod, predictor as pred_mod

    p1_prof = feat_mod.get_profile(mem, name1)
    p2_prof = feat_mod.get_profile(mem, name2)
    f1 = feat_mod.feature_vector(p1_prof)
    f2 = feat_mod.feature_vector(p2_prof)

    weights = mem.get("weights") or {}
    bias    = float(mem.get("bias", 0.0))

    s1 = pred_mod.weighted_score(weights, f1)
    s2 = pred_mod.weighted_score(weights, f2)

    # Include surface-aware ELO blend
    elo_contrib = pred_mod.elo_logit(mem, name1, name2, surface)
    z = (s1 - s2) + bias + elo_contrib
    return _sigmoid(z)


# ---------------------------------------------------------------------------
# 4. Transformer proxy (surface-conditioned attention on features)
# ---------------------------------------------------------------------------

# Attention heads: each surface emphasises different feature dimensions.
_SURFACE_HEADS: Dict[str, Dict[str, float]] = {
    "clay":  {"serve": 0.15, "return1": 0.35, "return2": 0.30, "recent": 0.20},
    "grass": {"serve": 0.45, "return1": 0.20, "return2": 0.15, "recent": 0.20},
    "hard":  {"serve": 0.30, "return1": 0.28, "return2": 0.22, "recent": 0.20},
}
_DEFAULT_HEAD = {"serve": 0.25, "return1": 0.28, "return2": 0.27, "recent": 0.20}

# Scale: maps raw feature-diff to logit range similar to ELO
_SCALE = 4.0


def transformer_proxy(
    mem: Dict[str, Any],
    name1: str,
    name2: str,
    surface: Optional[str] = None,
) -> float:
    """Surface-aware attention-weighted feature scoring (no deep learning).

    Mimics the 'which features matter here?' logic of attention heads by
    applying surface-dependent weights to player statistics.
    """
    head = _SURFACE_HEADS.get(surface or "", _DEFAULT_HEAD)
    players = mem.get("players") or {}
    p1 = players.get(name1) or {}
    p2 = players.get(name2) or {}

    score1 = sum(w * p1.get(k, 0.0) for k, w in head.items())
    score2 = sum(w * p2.get(k, 0.0) for k, w in head.items())
    return _sigmoid((score1 - score2) * _SCALE)
