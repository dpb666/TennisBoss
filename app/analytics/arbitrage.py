"""Arbitrage detection: positive EV across both sides (risk-free or near-risk-free)."""
from __future__ import annotations

from typing import Optional


def implied_prob_from_odds(decimal_odds: float) -> float:
	"""Convert decimal odds to implied probability."""
	if decimal_odds <= 1.0:
		return 0.0
	return 1.0 / decimal_odds


def check_arbitrage(
	decimal_odds_side1: float,
	decimal_odds_side2: float,
	threshold: float = 0.01,  # 1% edge to call it arb
) -> dict:
	"""Detect if both sides have positive EV (arbitrage opportunity).

	Arbitrage exists when: (1/odds1 + 1/odds2) < 1

	Args:
		decimal_odds_side1: Decimal odds for side 1
		decimal_odds_side2: Decimal odds for side 2 (opposite outcome)
		threshold: Minimum edge % to call it arbitrage

	Returns:
		{
			"is_arb": bool,
			"arb_pct": float (0-100),
			"stake_split": {
				"side1_pct": float,
				"side2_pct": float
			},
			"profit_at_stake_100": float,
			"recommendation": str
		}
	"""
	if decimal_odds_side1 <= 1.0 or decimal_odds_side2 <= 1.0:
		return {"error": "Invalid odds", "is_arb": False}

	implied1 = implied_prob_from_odds(decimal_odds_side1)
	implied2 = implied_prob_from_odds(decimal_odds_side2)

	# Total implied probability (includes vig)
	total_implied = implied1 + implied2

	# Arbitrage edge: how much < 1.0
	arb_edge = 1.0 - total_implied
	arb_pct = arb_edge * 100

	# Optimal stake allocation (Kelly-style)
	# Stake side1 at rate of implied2 / total
	stake_side1_pct = (implied2 / total_implied * 100) if total_implied > 0 else 50
	stake_side2_pct = 100 - stake_side1_pct

	# Profit at $100 total stake
	profit_per_stake_1 = (100 * stake_side1_pct / 100) * (decimal_odds_side1 - 1)
	profit_per_stake_2 = (100 * stake_side2_pct / 100) * (decimal_odds_side2 - 1)
	profit = profit_per_stake_1 + profit_per_stake_2 - 100

	is_arb = arb_pct >= threshold

	recommendation = "PASS"
	if is_arb:
		recommendation = f"ARBITRAGE: {arb_pct:.2f}% edge"

	return {
		"is_arb": is_arb,
		"arb_pct": round(arb_pct, 2),
		"stake_split": {
			"side1_pct": round(stake_side1_pct, 1),
			"side2_pct": round(stake_side2_pct, 1),
		},
		"profit_per_100_stake": round(profit, 2),
		"implied_total": round(total_implied, 4),
		"recommendation": recommendation,
	}


def multi_arb_check(
	markets: list[dict],
	threshold: float = 0.01,
) -> list[dict]:
	"""Check arbitrage across multiple bookmakers.

	Args:
		markets: List of {bookmaker, odds_side1, odds_side2}
		threshold: Minimum arb % to report

	Returns:
		List of arb opportunities across bookmaker pairs
	"""
	arbs = []
	for i, m1 in enumerate(markets):
		for m2 in markets[i + 1 :]:
			# Compare best odds across bookmakers
			best_odds_s1 = max(m1["odds_side1"], m2["odds_side1"])
			best_odds_s2 = max(m1["odds_side2"], m2["odds_side2"])

			result = check_arbitrage(best_odds_s1, best_odds_s2, threshold)
			if result.get("is_arb"):
				arbs.append(
					{
						"bookmakers": (m1["bookmaker"], m2["bookmaker"]),
						"side1_from": m1["bookmaker"] if m1["odds_side1"] > m2["odds_side1"] else m2["bookmaker"],
						"side2_from": m1["bookmaker"] if m1["odds_side2"] > m2["odds_side2"] else m2["bookmaker"],
						**result,
					}
				)

	return arbs
