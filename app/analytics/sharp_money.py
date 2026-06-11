"""Sharp money detection: volume anomalies, line movement, big bet signals."""
from __future__ import annotations

import time
from typing import Optional


class SharpMoneyDetector:
	"""Detect sharp money signals from volume and line movement."""

	def __init__(self):
		self.history: dict[str, list] = {}  # match_id -> list of snapshots

	def record_snapshot(
		self,
		match_id: str,
		current_odds: float,
		volume: float = 0.0,
		timestamp: Optional[float] = None,
	) -> None:
		"""Record market snapshot for trend analysis."""
		if match_id not in self.history:
			self.history[match_id] = []

		snapshot = {
			"ts": timestamp or time.time(),
			"odds": current_odds,
			"volume": volume,
		}
		self.history[match_id].append(snapshot)

		# Keep last 100 snapshots per match
		if len(self.history[match_id]) > 100:
			self.history[match_id] = self.history[match_id][-100:]

	def line_movement(self, match_id: str) -> dict:
		"""Calculate line movement (opening -> current)."""
		if match_id not in self.history or len(self.history[match_id]) < 2:
			return {"error": "Insufficient data", "movement_pct": 0}

		snapshots = self.history[match_id]
		opening = snapshots[0]["odds"]
		current = snapshots[-1]["odds"]

		movement_pct = ((current - opening) / opening * 100) if opening > 0 else 0

		return {
			"opening_odds": round(opening, 3),
			"current_odds": round(current, 3),
			"movement_pct": round(movement_pct, 2),
			"direction": "UP" if movement_pct > 0 else "DOWN" if movement_pct < 0 else "FLAT",
		}

	def volume_analysis(
		self,
		match_id: str,
		lookback_snapshots: int = 20,
	) -> dict:
		"""Analyze volume trend and volatility."""
		if match_id not in self.history:
			return {"error": "No data", "is_anomaly": False}

		snapshots = self.history[match_id]
		if len(snapshots) < lookback_snapshots:
			lookback_snapshots = len(snapshots)

		recent = snapshots[-lookback_snapshots:]
		volumes = [s["volume"] for s in recent]

		if not volumes or sum(volumes) == 0:
			return {
				"avg_volume": 0.0,
				"current_volume": 0.0,
				"volume_pct_change": 0.0,
				"is_anomaly": False,
			}

		avg_vol = sum(volumes) / len(volumes)
		current_vol = volumes[-1] if volumes else 0

		vol_change = ((current_vol - avg_vol) / avg_vol * 100) if avg_vol > 0 else 0

		# Anomaly: volume spike > 50% above average
		is_anomaly = vol_change > 50

		return {
			"avg_volume": round(avg_vol, 2),
			"current_volume": round(current_vol, 2),
			"volume_pct_change": round(vol_change, 2),
			"is_anomaly": is_anomaly,
			"anomaly_threshold_pct": 50,
		}

	def detect_sharp_signal(
		self,
		match_id: str,
		line_move_threshold: float = 2.0,  # % change
		volume_spike_threshold: float = 50.0,  # %
	) -> dict:
		"""Detect sharp money signal: line move + volume spike together."""
		movement = self.line_movement(match_id)
		volume = self.volume_analysis(match_id)

		if "error" in movement or "error" in volume:
			return {"is_sharp": False, "reason": "Insufficient data"}

		move_abs = abs(movement.get("movement_pct", 0))
		vol_spike = volume.get("volume_pct_change", 0)

		# Sharp signal: significant move + significant volume
		is_sharp = (move_abs >= line_move_threshold) and (vol_spike >= volume_spike_threshold)

		confidence = 0.0
		if move_abs >= line_move_threshold:
			confidence += 0.5
		if vol_spike >= volume_spike_threshold:
			confidence += 0.5

		reason_parts = []
		if move_abs >= line_move_threshold:
			reason_parts.append("LINE_MOVE")
		if vol_spike >= volume_spike_threshold:
			reason_parts.append("VOLUME_SPIKE")

		return {
			"is_sharp": is_sharp,
			"confidence": round(confidence, 2),
			"line_movement_pct": movement["movement_pct"],
			"volume_spike_pct": vol_spike,
			"direction": movement.get("direction", "UNKNOWN"),
			"reason": " + ".join(reason_parts) if reason_parts else "NO_SIGNAL",
		}

	def big_bet_signal(
		self,
		match_id: str,
		big_bet_volume_threshold: float = 1000.0,  # $ or units
	) -> dict:
		"""Detect big bet: single stake much larger than average."""
		if match_id not in self.history or len(self.history[match_id]) == 0:
			return {"is_big_bet": False, "reason": "No data"}

		snapshots = self.history[match_id]
		volumes = [s["volume"] for s in snapshots]

		if not volumes or sum(volumes) == 0:
			return {"is_big_bet": False, "reason": "No volume data"}

		avg_vol = sum(volumes) / len(volumes)
		latest_vol = volumes[-1]

		is_big = latest_vol > big_bet_volume_threshold

		return {
			"is_big_bet": is_big,
			"latest_volume": round(latest_vol, 2),
			"average_volume": round(avg_vol, 2),
			"multiple_of_avg": round(latest_vol / avg_vol, 2) if avg_vol > 0 else 0,
			"threshold": big_bet_volume_threshold,
		}
