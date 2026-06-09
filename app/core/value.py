"""Expected Value engine.

EV = (probability × decimal_odds) − 1

EV > 0   → positive expected value
EV > 0.05 → minimum threshold to place a bet
"""
from __future__ import annotations

from typing import Optional


MIN_EV = 0.05          # minimum EV to recommend a bet
MIN_CONFIDENCE = 0.40  # below this confidence, skip regardless of EV
MIN_PROB = 0.52        # never bet near coin-flip territory


def expected_value(prob: float, decimal_odds: float) -> float:
    """EV = prob × odds − 1.  Positive means profitable long-term."""
    return round(prob * decimal_odds - 1.0, 4)


def should_bet(
    ev: float,
    prob: float,
    confidence: float,
    min_ev: float = MIN_EV,
    min_confidence: float = MIN_CONFIDENCE,
    min_prob: float = MIN_PROB,
) -> tuple[bool, str]:
    """Return (bet, reason).

    All three filters must pass:
    1. EV ≥ min_ev
    2. confidence ≥ min_confidence
    3. probability ≥ min_prob (no near-coin-flip bets)
    """
    if prob < min_prob:
        return False, f"prob {prob:.2%} < min {min_prob:.0%}"
    if confidence < min_confidence:
        return False, f"confidence {confidence:.2f} < min {min_confidence:.2f}"
    if ev < min_ev:
        return False, f"EV {ev:.2%} < min {min_ev:.0%}"
    return True, f"EV={ev:.2%}  prob={prob:.2%}  conf={confidence:.2f}"


def best_side(
    prob1: float,
    odds1: float,
    odds2: float,
) -> tuple[int, float, float]:
    """Return (side, ev, odds) for the better value bet.

    side=1 → bet player1, side=2 → bet player2.
    """
    ev1 = expected_value(prob1, odds1)
    ev2 = expected_value(1.0 - prob1, odds2)
    if ev1 >= ev2:
        return 1, ev1, odds1
    return 2, ev2, odds2
