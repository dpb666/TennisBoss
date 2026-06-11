"""Hedge manager: calculate and execute hedge orders on live positions."""
from __future__ import annotations

from typing import Optional


class HedgeManager:
	"""Manage hedging opportunities on open positions."""

	def calculate_hedge(
		self,
		original_stake: float,
		original_odds: float,
		current_odds: float,
		new_model_prob: Optional[float] = None,
	) -> dict:
		"""Calculate hedge opportunity.

		If we bet at original_odds and odds have moved, closing now locks in a profit/loss.

		Args:
			original_stake: Initial stake placed
			original_odds: Odds at placement
			current_odds: Current market odds for same outcome
			new_model_prob: If we want to bet opposite side

		Returns:
			Hedge details: stake to lay, odds to lay at, profit/loss if closed
		"""
		# P&L if we close the original position now
		if current_odds > original_odds:
			# Odds improved: we can close at better odds, lock in profit
			pnl_if_close = original_stake * (current_odds - original_odds)
		else:
			# Odds worsened: we take a loss if we close
			pnl_if_close = -original_stake * (original_odds - current_odds)

		# To hedge: lay the stake at current odds
		# This covers the original bet and locks in P&L
		lay_stake = original_stake * current_odds / original_odds

		return {
			"original": {
				"stake": original_stake,
				"odds": original_odds,
			},
			"current": {
				"odds": current_odds,
			},
			"hedge": {
				"stake_to_lay": round(lay_stake, 2),
				"lay_odds": round(current_odds, 3),
				"pnl_if_closed": round(pnl_if_close, 2),
				"is_profitable_to_close": pnl_if_close > 0,
			},
		}

	def hedge_with_opposite_bet(
		self,
		original_stake: float,
		original_odds_for: float,
		current_odds_against: float,
		max_loss_tolerance: float = 0.0,  # 0 = no loss
	) -> dict:
		"""Hedge original bet by betting opposite side.

		Args:
			original_stake: Stake on original bet
			original_odds_for: Original odds for our side
			current_odds_against: Odds for opposite side now
			max_loss_tolerance: Max loss we'll accept

		Returns:
			Hedge bet details
		"""
		# Calculate required hedge stake to neutralize downside
		# If we lose original, we win hedge
		# If we win original, we lose hedge
		# Goal: net profit or break-even

		hedge_stake = original_stake * original_odds_for / current_odds_against

		# P&L scenarios
		pnl_original_wins = original_stake * (original_odds_for - 1) - hedge_stake
		pnl_original_loses = -original_stake - hedge_stake * (1 - current_odds_against)

		return {
			"original": {
				"stake": original_stake,
				"odds": original_odds_for,
			},
			"hedge": {
				"stake_to_place": round(hedge_stake, 2),
				"against_odds": round(current_odds_against, 3),
				"player": "OPPOSITE",
			},
			"scenarios": {
				"if_original_wins": {
					"profit": round(pnl_original_wins, 2),
					"description": "Original bet wins, hedge loses",
				},
				"if_original_loses": {
					"profit": round(pnl_original_loses, 2),
					"description": "Original bet loses, hedge wins",
				},
			},
			"recommendation": (
				"HEDGE" if abs(pnl_original_loses) < max_loss_tolerance
				else "CONSIDER_HEDGE"
			),
		}

	def batch_hedge_check(
		self,
		positions: list[dict],  # List of {stake, odds, current_odds}
	) -> list[dict]:
		"""Check all positions for hedge opportunities."""
		hedges = []
		for pos in positions:
			hedge = self.calculate_hedge(
				pos["stake"],
				pos["odds"],
				pos.get("current_odds", pos["odds"]),
			)
			hedges.append(hedge)

		return hedges

	def hedge_summary(
		self,
		positions: list[dict],
		profitability_threshold: float = 0.0,  # Only hedge if +EV
	) -> dict:
		"""Summary of hedge opportunities across portfolio."""
		hedges = self.batch_hedge_check(positions)

		profitable_hedges = [
			h for h in hedges
			if h["hedge"]["pnl_if_closed"] > profitability_threshold
		]

		total_available_pnl = sum(h["hedge"]["pnl_if_closed"] for h in profitable_hedges)

		return {
			"total_positions": len(positions),
			"hedgeable_profitable": len(profitable_hedges),
			"total_available_pnl": round(total_available_pnl, 2),
			"recommendation": (
				"HEDGE_ALL" if total_available_pnl > 0
				else "HOLD_POSITIONS"
			),
		}
