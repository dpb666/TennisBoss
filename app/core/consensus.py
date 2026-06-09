"""Consensus layer: weighted combination of all probability models.

ELO gets slightly more weight — it proved best in backtests (67% acc).
Bayesian can be skipped when no odds are available.
"""
from __future__ import annotations

import math
import statistics
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from .models import (
    elo_probability,
    bayesian_adjustment,
    feature_probability,
    transformer_proxy,
)

# Default model weights (must sum to 1.0).
DEFAULT_WEIGHTS = {
    "elo":         0.30,
    "bayesian":    0.25,
    "features":    0.25,
    "transformer": 0.20,
}

# When no odds available, redistribute Bayesian weight to ELO.
NO_ODDS_WEIGHTS = {
    "elo":         0.40,
    "bayesian":    0.00,
    "features":    0.35,
    "transformer": 0.25,
}


@dataclass
class ConsensusResult:
    probability: float          # final blended probability
    confidence:  float          # 0–1 : high = models agree and prob far from 0.5
    agreement:   float          # fraction of models on the same side
    model_probs: Dict[str, float] = field(default_factory=dict)
    weights_used: Dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "probability":  round(self.probability, 4),
            "confidence":   round(self.confidence, 4),
            "agreement":    round(self.agreement, 4),
            "model_probs":  {k: round(v, 4) for k, v in self.model_probs.items()},
            "weights_used": self.weights_used,
        }


def _confidence(probs: list[float], final: float) -> float:
    """Confidence = certainty × agreement-penalty.

    High when all models agree AND the final prob is far from 50%.
    """
    certainty = abs(final - 0.5) * 2          # 0 (50%) → 1 (100% or 0%)
    if len(probs) > 1:
        std = statistics.stdev(probs)
        agreement_factor = max(0.0, 1.0 - std * 4)  # std=0.25 → factor=0
    else:
        agreement_factor = 1.0
    return round(certainty * agreement_factor, 4)


def _agreement(probs: list[float], side: bool) -> float:
    """Fraction of models predicting the same side as the consensus."""
    same = sum(1 for p in probs if (p >= 0.5) == side)
    return same / len(probs)


def combine(
    mem: Dict[str, Any],
    name1: str,
    name2: str,
    surface: Optional[str] = None,
    market_odds1: Optional[float] = None,
    market_odds2: Optional[float] = None,
    weights: Optional[Dict[str, float]] = None,
) -> ConsensusResult:
    """Run all models and return blended consensus."""
    has_odds = (market_odds1 is not None and market_odds2 is not None
                and market_odds1 > 1.0 and market_odds2 > 1.0)

    w = weights or (DEFAULT_WEIGHTS if has_odds else NO_ODDS_WEIGHTS)

    # --- ELO ---
    p_elo = elo_probability(mem, name1, name2, surface)

    # --- Feature model ---
    p_feat = feature_probability(mem, name1, name2, surface)

    # --- Transformer proxy ---
    p_trans = transformer_proxy(mem, name1, name2, surface)

    # --- Bayesian (requires odds) ---
    if has_odds:
        # Use ELO as the model prior for Bayesian adjustment
        p_bayes = bayesian_adjustment(p_elo, market_odds1, market_odds2)
    else:
        p_bayes = None

    # Weighted blend
    model_probs: Dict[str, float] = {
        "elo":         p_elo,
        "features":    p_feat,
        "transformer": p_trans,
    }
    if p_bayes is not None:
        model_probs["bayesian"] = p_bayes

    total_w = sum(w[k] for k in model_probs)
    final = sum(w[k] * v for k, v in model_probs.items()) / total_w

    probs_list = list(model_probs.values())
    side_is_p1 = final >= 0.5

    return ConsensusResult(
        probability   = round(final, 4),
        confidence    = _confidence(probs_list, final),
        agreement     = round(_agreement(probs_list, side_is_p1), 4),
        model_probs   = model_probs,
        weights_used  = {k: w[k] for k in model_probs},
    )
