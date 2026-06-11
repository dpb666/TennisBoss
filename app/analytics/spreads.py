"""Live spread analysis: implied prob vs model prob, EV calculation."""
from __future__ import annotations

from typing import Optional
from app.core import value as value_mod


def implied_probability(decimal_odds: float) -> float:
	"""Convert decimal odds to implied probability (includes vig)."""
	if decimal_odds <= 1.0:
		return 0.0
	return 1.0 / decimal_odds


def spread_analysis(
	model_prob: float,
	decimal_odds_model_side: float,
	decimal_odds_opposite_side: float,
	confidence: float = 0.75,
) -> dict:
	"""Analyze spread between model and market.

	Args:
		model_prob: Our estimated win probability (0-1)
		decimal_odds_model_side: Odds for our predicted winner
		decimal_odds_opposite_side: Odds for the opposite outcome
		confidence: Model confidence (0-1)

	Returns:
		{
			"model_prob": 0.58,
			"implied_prob_our_side": 0.52,
			"implied_prob_opposite": 0.48,
			"ev": 0.0675,
			"edge_pct": 6.0,
			"spread_pct": 6.0,
			"confidence_weighted_ev": 0.050,
			"market_efficiency": 0.95,  # 1.0 = perfectly efficient
			"recommendation": "BET"
		}
	"""
	if not (0 < model_prob < 1) or confidence < 0 or confidence > 1:
		return {"error": "Invalid inputs"}

	implied_our = implied_probability(decimal_odds_model_side)
	implied_opp = implied_probability(decimal_odds_opposite_side)

	# Total vig (market inefficiency)
	total_vig = (implied_our + implied_opp) - 1.0

	# EV on our side
	ev = value_mod.expected_value(model_prob, decimal_odds_model_side)

	# Spread: how far our model is from market
	spread = (model_prob - implied_our) * 100

	# Confidence-weighted EV (reduce if low confidence)
	weighted_ev = ev * confidence

	# Market efficiency: 1.0 = perfectly efficient (all vig used), < 1.0 = inefficient
	market_eff = 1.0 - total_vig if total_vig > 0 else 1.0

	recommendation = "PASS"
	if ev >= value_mod.MIN_EV and confidence >= value_mod.MIN_CONFIDENCE:
		recommendation = "BET"

	return {
		"model_prob": round(model_prob, 4),
		"implied_prob_our_side": round(implied_our, 4),
		"implied_prob_opposite": round(implied_opp, 4),
		"ev": round(ev, 4),
		"edge_pct": round(spread, 2),
		"spread_pct": round(spread, 2),
		"confidence_weighted_ev": round(weighted_ev, 4),
		"total_vig_pct": round(total_vig * 100, 2),
		"market_efficiency": round(market_eff, 3),
		"recommendation": recommendation,
	}


def compare_spreads(
	prob1: float,
	prob2: float,
	odds1: float,
	odds2: float,
	confidence: float = 0.75,
) -> dict:
	"""Compare spreads across both sides of a match (for context)."""
	side1 = spread_analysis(prob1, odds1, odds2, confidence)
	side2 = spread_analysis(prob2, odds2, odds1, confidence)

	return {
		"side1": side1,
		"side2": side2,
		"best_side": "side1" if (side1.get("ev", 0) > side2.get("ev", 0)) else "side2",
		"combined_edge": round(
			max(side1.get("ev", 0), side2.get("ev", 0)), 4
		),
	}
