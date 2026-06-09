"""Pipeline orchestrator: input → models → consensus → EV → risk → decision."""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from .consensus import combine, ConsensusResult
from .value import expected_value, should_bet, best_side
from .risk import RiskEngine, kelly_stake

logger = logging.getLogger("tennisboss.engine")

# Module-level singleton — replaced at startup with real bankroll.
_risk_engine: Optional[RiskEngine] = None


def get_risk_engine() -> RiskEngine:
    global _risk_engine
    if _risk_engine is None:
        _risk_engine = RiskEngine()
    return _risk_engine


def init_engine(bankroll: float = 1000.0) -> RiskEngine:
    global _risk_engine
    _risk_engine = RiskEngine(bankroll=bankroll)
    return _risk_engine


class BettingEngine:
    """Stateless analysis wrapper.  Uses the module-level RiskEngine for limits."""

    def __init__(self, mem: Dict[str, Any]) -> None:
        self.mem = mem

    def analyze_match(
        self,
        player1: str,
        player2: str,
        surface: Optional[str] = None,
        odds1: Optional[float] = None,
        odds2: Optional[float] = None,
        bankroll: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Full pipeline: returns structured betting decision JSON."""
        match_label = f"{player1} vs {player2}"
        surface_key = (surface or "").lower() or None

        # --- Consensus ---
        consensus: ConsensusResult = combine(
            mem          = self.mem,
            name1        = player1,
            name2        = player2,
            surface      = surface_key,
            market_odds1 = odds1,
            market_odds2 = odds2,
        )
        prob = consensus.probability

        # --- EV ---
        has_odds = odds1 and odds2 and odds1 > 1.0 and odds2 > 1.0
        if has_odds:
            side_idx, ev, bet_odds = best_side(prob, odds1, odds2)
            side_name = player1 if side_idx == 1 else player2
            side_prob  = prob if side_idx == 1 else 1.0 - prob
        else:
            ev        = 0.0
            bet_odds  = 0.0
            side_name = player1 if prob >= 0.5 else player2
            side_prob  = prob if prob >= 0.5 else 1.0 - prob
            side_idx   = 1 if prob >= 0.5 else 2

        bet_ok, bet_reason = should_bet(ev, prob if side_idx == 1 else 1 - prob,
                                         consensus.confidence)

        # --- Kelly stake ---
        risk = get_risk_engine()
        _bankroll = bankroll or risk.bankroll
        raw_stake = kelly_stake(side_prob, bet_odds, _bankroll) if (bet_ok and has_odds) else 0.0

        # --- Risk approval ---
        if bet_ok and raw_stake > 0:
            approved, risk_reason = risk.approve(raw_stake, side_prob, bet_odds, match_label)
        else:
            approved, risk_reason = False, bet_reason

        final_bet   = bet_ok and approved
        final_stake = raw_stake if final_bet else 0.0

        logger.info(
            "DECISION %-40s  prob=%.3f  ev=%.3f  stake=%.2f  bet=%s  [%s]",
            match_label, prob, ev, final_stake, final_bet, risk_reason,
        )

        return {
            "match":       match_label,
            "surface":     surface_key or "unknown",
            "probability": prob,
            "ev":          round(ev, 4),
            "bet":         final_bet,
            "stake":       final_stake,
            "side":        side_name if final_bet else None,
            "odds":        bet_odds if final_bet else None,
            "confidence":  consensus.confidence,
            "agreement":   consensus.agreement,
            "reason":      risk_reason,
            "details": {
                "model_probs":   consensus.model_probs,
                "weights_used":  consensus.weights_used,
                "risk": {
                    "bankroll":    round(risk.bankroll, 2),
                    "exposure":    risk.exposure,
                    "daily_pnl":   risk.daily_pnl,
                    "drawdown_pct": risk.drawdown_pct,
                },
            },
        }
