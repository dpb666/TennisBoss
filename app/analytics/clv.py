"""Closing Line Value (CLV) tracking: model performance vs market closing odds."""
from __future__ import annotations

import time
from typing import Optional


class CLVTracker:
	"""Track closing line value to calibrate model reliability."""

	def __init__(self):
		self.records: list[dict] = []

	def record_analysis(
		self,
		match_id: str,
		analysis_odds: float,
		model_prob: float,
		confidence: float,
		timestamp: Optional[float] = None,
	) -> None:
		"""Record analysis at time of bet decision."""
		self.records.append({
			"match_id": match_id,
			"analysis_odds": analysis_odds,
			"model_prob": model_prob,
			"confidence": confidence,
			"analysis_ts": timestamp or time.time(),
			"closing_odds": None,
			"closing_ts": None,
			"clv": None,
			"clv_pct": None,
			"won": None,  # Fill after match settles
		})

	def record_closing(
		self,
		match_id: str,
		closing_odds: float,
		timestamp: Optional[float] = None,
	) -> dict:
		"""Record closing odds (just before match starts)."""
		record = None
		for r in self.records:
			if r["match_id"] == match_id:
				record = r
				break

		if not record:
			return {"error": f"Match {match_id} not found in analysis records"}

		record["closing_odds"] = closing_odds
		record["closing_ts"] = timestamp or time.time()

		# Calculate CLV
		if record["analysis_odds"] > 0:
			clv = closing_odds - record["analysis_odds"]
			clv_pct = (clv / record["analysis_odds"]) * 100
			record["clv"] = clv
			record["clv_pct"] = clv_pct

			return {
				"match_id": match_id,
				"clv": round(clv, 3),
				"clv_pct": round(clv_pct, 2),
				"analysis_odds": record["analysis_odds"],
				"closing_odds": closing_odds,
			}

		return {"error": "Invalid analysis odds"}

	def record_settlement(
		self,
		match_id: str,
		won: bool,
	) -> None:
		"""Record match result."""
		for r in self.records:
			if r["match_id"] == match_id:
				r["won"] = won
				break

	def clv_stats_by_confidence(self) -> dict:
		"""Aggregate CLV stats by model confidence tier."""
		tiers = {
			"high": [],  # confidence >= 0.75
			"medium": [],  # 0.60-0.74
			"low": [],  # < 0.60
		}

		for r in self.records:
			if r["clv_pct"] is None:
				continue

			conf = r["confidence"]
			if conf >= 0.75:
				tiers["high"].append(r)
			elif conf >= 0.60:
				tiers["medium"].append(r)
			else:
				tiers["low"].append(r)

		stats = {}
		for tier_name, records in tiers.items():
			if not records:
				stats[tier_name] = {"count": 0}
				continue

			clvs = [r["clv_pct"] for r in records]
			wins = [r["won"] for r in records if r["won"] is not None]

			stats[tier_name] = {
				"count": len(records),
				"avg_clv_pct": round(sum(clvs) / len(clvs), 2),
				"win_rate": round(sum(wins) / len(wins) * 100, 1) if wins else None,
				"beat_closing": sum(1 for c in clvs if c > 0),
			}

		return stats

	def clv_by_model(self) -> dict:
		"""CLV performance by model (if available in metadata)."""
		# Placeholder: extend with model field tracking if needed
		return {}

	def all_records(self) -> list[dict]:
		"""Return all CLV records for analysis."""
		return self.records

	def records_settled(self) -> list[dict]:
		"""Return only settled matches."""
		return [r for r in self.records if r["won"] is not None]
