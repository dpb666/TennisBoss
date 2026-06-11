"""Portfolio Greeks: Delta, Vega, Theta for betting portfolios."""
from __future__ import annotations

from typing import Optional


class PortfolioGreeks:
	"""Calculate portfolio-level risk metrics."""

	@staticmethod
	def calculate_delta(
		positions: list[dict],  # {player, stake, prob, odds}
		focus_player: Optional[str] = None,
	) -> dict:
		"""Delta = net exposure to player winning.

		Positive delta = we win if player wins
		Negative delta = we win if player loses
		"""
		total_delta = 0.0
		delta_by_player = {}

		for pos in positions:
			player = pos["player"]
			stake = pos["stake"]
			prob = pos.get("model_prob", 0.5)
			odds = pos.get("odds", 1.0)

			# Delta for this position
			position_delta = stake * prob * (odds - 1)

			total_delta += position_delta

			if player not in delta_by_player:
				delta_by_player[player] = 0.0
			delta_by_player[player] += position_delta

		return {
			"total_delta": round(total_delta, 2),
			"delta_by_player": {k: round(v, 2) for k, v in delta_by_player.items()},
			"positive_exposure": total_delta > 0,
		}

	@staticmethod
	def calculate_vega(
		positions: list[dict],  # {stake, confidence}
	) -> dict:
		"""Vega = exposure to model confidence changes.

		High confidence → tight portfolio (low vega)
		Mixed confidence → exposed to confidence drops (high vega)
		"""
		if not positions:
			return {"vega": 0.0, "avg_confidence": 0.0}

		total_stake = sum(p["stake"] for p in positions)
		avg_confidence = sum(p.get("confidence", 0.75) * p["stake"] for p in positions) / total_stake if total_stake > 0 else 0.75

		# Vega = standard deviation of confidence (position-weighted)
		confidence_variance = sum(
			p["stake"] * (p.get("confidence", 0.75) - avg_confidence) ** 2
			for p in positions
		) / total_stake if total_stake > 0 else 0.0

		vega = confidence_variance ** 0.5

		return {
			"vega": round(vega, 4),
			"avg_confidence": round(avg_confidence, 3),
			"vega_interpretation": (
				"LOW" if vega < 0.10
				else "MEDIUM" if vega < 0.20
				else "HIGH"
			),
		}

	@staticmethod
	def calculate_theta(
		positions: list[dict],  # {match_id, opened_at, current_ts}
		current_ts: float,
	) -> dict:
		"""Theta = time decay (odds shift as match approaches).

		Early match → low theta (lots of time for moves)
		Minutes before → high theta (odds locked in)
		"""
		import time

		if not positions:
			return {"theta": 0.0, "avg_time_to_match": 0.0}

		total_time_to_match = 0.0
		for pos in positions:
			opened = pos.get("opened_at", current_ts)
			time_elapsed = current_ts - opened
			total_time_to_match += time_elapsed

		avg_time = total_time_to_match / len(positions) if positions else 0.0
		hours_to_match = avg_time / 3600

		# Theta: higher when match is imminent (less time for line to move)
		# Approximate: theta ~= 1 / hours_to_match (higher = sooner)
		theta = 1.0 / (max(hours_to_match, 0.1)) if hours_to_match > 0 else 0.0

		return {
			"theta": round(theta, 3),
			"avg_hours_to_match": round(hours_to_match, 1),
			"theta_interpretation": (
				"HIGH" if hours_to_match < 1
				else "MEDIUM" if hours_to_match < 6
				else "LOW"
			),
		}

	@staticmethod
	def portfolio_summary(
		positions: list[dict],
		current_ts: Optional[float] = None,
	) -> dict:
		"""Full Greeks summary."""
		import time
		if current_ts is None:
			current_ts = time.time()

		delta = PortfolioGreeks.calculate_delta(positions)
		vega = PortfolioGreeks.calculate_vega(positions)
		theta = PortfolioGreeks.calculate_theta(positions, current_ts)

		total_stake = sum(p["stake"] for p in positions)
		correlation = PortfolioGreeks._correlation_estimate(positions)

		return {
			"delta": delta,
			"vega": vega,
			"theta": theta,
			"total_exposure": round(total_stake, 2),
			"num_positions": len(positions),
			"portfolio_correlation": round(correlation, 3),
			"hedge_ratio": round(1.0 - abs(delta["total_delta"]) / max(total_stake, 1.0), 3),
		}

	@staticmethod
	def _correlation_estimate(positions: list[dict]) -> float:
		"""Estimate portfolio correlation (0=uncorrelated, 1=all same)."""
		if len(positions) < 2:
			return 0.0

		# Simple estimate: how many positions are on same player
		players = [p["player"] for p in positions]
		unique_players = set(players)

		correlation = 1.0 - (len(unique_players) / len(positions))
		return max(0, min(correlation, 1.0))
