"""Scenario analysis: stress testing portfolio."""
from __future__ import annotations

from typing import Optional


class ScenarioAnalyzer:
	"""Stress test portfolio under different scenarios."""

	@staticmethod
	def max_loss_scenario(positions: list[dict]) -> dict:
		"""Calculate maximum possible loss (all bets lost)."""
		total_stake = sum(p["stake"] for p in positions)
		max_loss = -total_stake

		return {
			"scenario": "ALL_LOSSES",
			"description": "Every bet loses",
			"max_loss": round(max_loss, 2),
			"loss_pct_of_portfolio": round((max_loss / total_stake * 100) if total_stake > 0 else 0, 1),
		}

	@staticmethod
	def best_case_scenario(positions: list[dict]) -> dict:
		"""Calculate maximum possible profit (all bets win)."""
		total_stake = sum(p["stake"] for p in positions)
		max_profit = sum(p["stake"] * (p.get("odds", 2.0) - 1) for p in positions)

		return {
			"scenario": "ALL_WINS",
			"description": "Every bet wins",
			"max_profit": round(max_profit, 2),
			"profit_pct_of_portfolio": round((max_profit / total_stake * 100) if total_stake > 0 else 0, 1),
		}

	@staticmethod
	def favorites_lost_scenario(positions: list[dict]) -> dict:
		"""Stress test: all favorites lose (value reversal)."""
		loss = 0.0
		for p in positions:
			# Assume prob > 0.55 = favorite
			if p.get("model_prob", 0.5) > 0.55:
				loss -= p["stake"]
			else:
				# Underdog wins
				loss += p["stake"] * (p.get("odds", 2.0) - 1)

		return {
			"scenario": "FAVORITES_LOSE",
			"description": "All favorites lose, underdogs win",
			"pnl": round(loss, 2),
		}

	@staticmethod
	def odds_collapse_scenario(
		positions: list[dict],
		odds_move_pct: float = -0.20,  # -20% odds movement
	) -> dict:
		"""Stress test: odds move adversely before settlement."""
		loss = 0.0
		for p in positions:
			original_odds = p.get("odds", 2.0)
			moved_odds = original_odds * (1 + odds_move_pct)
			stake = p["stake"]

			# If we can close now at moved odds, P&L is:
			pnl = stake * (moved_odds - original_odds)
			loss += pnl

		return {
			"scenario": "ODDS_COLLAPSE",
			"description": f"Odds move {odds_move_pct*100:.0f}% against us",
			"pnl_if_close": round(loss, 2),
			"odds_move_pct": odds_move_pct * 100,
		}

	@staticmethod
	def volatility_shock_scenario(
		positions: list[dict],
		confidence_drop: float = 0.15,  # -15% confidence
	) -> dict:
		"""Stress test: model confidence drops."""
		# In reality, lower confidence = we'd want smaller stakes
		# But with fixed stakes, implied value changes
		value_lost = 0.0
		for p in positions:
			stake = p["stake"]
			original_conf = p.get("confidence", 0.75)
			new_conf = max(0, original_conf - confidence_drop)
			conf_drop_impact = (original_conf - new_conf) * stake

			value_lost += conf_drop_impact

		return {
			"scenario": "CONFIDENCE_DROP",
			"description": f"Model confidence drops {confidence_drop*100:.0f}%",
			"value_at_risk": round(value_lost, 2),
			"confidence_drop_pct": confidence_drop * 100,
		}

	@staticmethod
	def var_cvar(
		positions: list[dict],
		confidence_level: float = 0.95,  # 95% VaR
	) -> dict:
		"""Value at Risk (VaR) and Conditional Value at Risk (CVaR).

		VaR(95%) = loss at 95th percentile
		CVaR(95%) = average loss in worst 5% scenarios
		"""
		# Simplified: treat worst case as 1-2 standard deviations
		# In real portfolio theory, this uses historical returns
		total_stake = sum(p["stake"] for p in positions)
		avg_prob = sum(p.get("model_prob", 0.5) * p["stake"] for p in positions) / total_stake if total_stake > 0 else 0.5

		# Worst case: prob is 1 std dev below mean
		worst_prob = max(0, avg_prob - 0.10)
		var_loss = -total_stake * worst_prob

		# CVaR: average of worst few outcomes
		cvar_loss = -total_stake * 0.8 * worst_prob  # Rough estimate

		return {
			"var_95_pct": round(var_loss, 2),
			"cvar_95_pct": round(cvar_loss, 2),
			"interpretation": f"95% chance loss <= ${abs(var_loss):.2f}",
			"expected_shortfall": round(cvar_loss, 2),
		}

	@staticmethod
	def full_stress_test(
		positions: list[dict],
		bankroll: float,
	) -> dict:
		"""Run all stress scenarios and summarize."""
		scenarios = [
			ScenarioAnalyzer.max_loss_scenario(positions),
			ScenarioAnalyzer.best_case_scenario(positions),
			ScenarioAnalyzer.favorites_lost_scenario(positions),
			ScenarioAnalyzer.odds_collapse_scenario(positions),
			ScenarioAnalyzer.volatility_shock_scenario(positions),
		]

		var_cvar = ScenarioAnalyzer.var_cvar(positions)

		worst_case = scenarios[0]["max_loss"]
		best_case = scenarios[1]["max_profit"]

		return {
			"bankroll": round(bankroll, 2),
			"scenarios": scenarios,
			"risk_metrics": var_cvar,
			"worst_case_loss": round(worst_case, 2),
			"worst_case_loss_pct": round((worst_case / bankroll * 100) if bankroll > 0 else 0, 1),
			"best_case_gain": round(best_case, 2),
			"best_case_gain_pct": round((best_case / bankroll * 100) if bankroll > 0 else 0, 1),
			"risk_reward_ratio": round(best_case / abs(worst_case), 2) if worst_case != 0 else 0,
		}
