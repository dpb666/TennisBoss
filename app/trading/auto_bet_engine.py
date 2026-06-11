"""Auto-bet engine: conditional placement when EV + confidence thresholds met."""
from __future__ import annotations

from typing import Optional
from app.core import value as value_mod
from app.analytics import spreads


class AutoBetEngine:
	"""Auto-execute bets when conditions are met."""

	def __init__(
		self,
		min_ev: float = 0.05,
		min_confidence: float = 0.60,
		max_stake_pct_of_bankroll: float = 0.05,  # Kelly-ish 5% max
	):
		self.min_ev = min_ev
		self.min_confidence = min_confidence
		self.max_stake_pct = max_stake_pct_of_bankroll
		self.decisions: list[dict] = []

	def should_place_bet(
		self,
		model_prob: float,
		odds: float,
		confidence: float,
		spread_data: Optional[dict] = None,
	) -> tuple[bool, str, float]:
		"""Decide if bet should auto-execute.

		Returns: (should_bet, reason, recommended_stake_pct)
		"""
		ev = value_mod.expected_value(model_prob, odds)

		# Check conditions
		if confidence < self.min_confidence:
			return False, f"confidence {confidence:.2f} < min {self.min_confidence:.2f}", 0.0

		if ev < self.min_ev:
			return False, f"EV {ev:.4f} < min {self.min_ev:.4f}", 0.0

		# Confidence-weighted stake
		stake_pct = confidence * self.max_stake_pct
		stake_pct = min(stake_pct, self.max_stake_pct)

		return True, f"AUTO_BET EV={ev:.4f} conf={confidence:.2f}", stake_pct

	def place_bet(
		self,
		match_id: str,
		player: str,
		model_prob: float,
		odds: float,
		confidence: float,
		bankroll: float,
	) -> dict:
		"""Execute auto-bet and record decision."""
		should_bet, reason, stake_pct = self.should_place_bet(
			model_prob, odds, confidence
		)

		stake = bankroll * stake_pct

		decision = {
			"match_id": match_id,
			"player": player,
			"model_prob": model_prob,
			"odds": odds,
			"confidence": confidence,
			"should_place": should_bet,
			"reason": reason,
			"stake_pct": stake_pct,
			"stake_amount": stake,
			"status": "APPROVED" if should_bet else "REJECTED",
		}

		self.decisions.append(decision)

		return decision

	def batch_analyze(
		self,
		matches: list[dict],
		bankroll: float,
	) -> list[dict]:
		"""Analyze multiple matches for auto-bet approval."""
		results = []
		for match in matches:
			result = self.place_bet(
				match_id=match["match_id"],
				player=match["player"],
				model_prob=match["prob"],
				odds=match["odds"],
				confidence=match.get("confidence", 0.75),
				bankroll=bankroll,
			)
			results.append(result)

		return results

	def get_decisions(self, status: Optional[str] = None) -> list[dict]:
		"""Retrieve recorded decisions."""
		if status:
			return [d for d in self.decisions if d["status"] == status]
		return self.decisions
