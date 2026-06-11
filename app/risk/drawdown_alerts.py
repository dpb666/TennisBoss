"""Drawdown monitoring and Kelly scaling."""
from __future__ import annotations

from typing import Optional


class DrawdownAlerts:
	"""Monitor and alert on portfolio drawdown."""

	def __init__(
		self,
		peak_bankroll: float = 1000.0,
		yellow_threshold: float = 0.025,  # 2.5%
		orange_threshold: float = 0.05,  # 5%
		red_threshold: float = 0.075,  # 7.5%
	):
		self.peak_bankroll = peak_bankroll
		self.yellow = yellow_threshold
		self.orange = orange_threshold
		self.red = red_threshold
		self.current_bankroll = peak_bankroll

	def update_bankroll(self, current_bankroll: float) -> None:
		"""Update current bankroll and track peak."""
		self.current_bankroll = current_bankroll
		if current_bankroll > self.peak_bankroll:
			self.peak_bankroll = current_bankroll

	def drawdown_pct(self) -> float:
		"""Current drawdown as percentage."""
		if self.peak_bankroll <= 0:
			return 0.0
		return (self.current_bankroll - self.peak_bankroll) / self.peak_bankroll

	def drawdown_alert(self) -> dict:
		"""Check drawdown and return alert level."""
		dd = self.drawdown_pct()
		dd_abs = abs(dd)

		if dd >= 0:
			return {
				"status": "NO_DRAWDOWN",
				"tier": "green",
				"drawdown_pct": 0.0,
				"kelly_scale": 1.0,
				"message": "Portfolio at or above peak.",
			}

		elif dd_abs < self.yellow:
			return {
				"status": "MINOR_DRAWDOWN",
				"tier": "green",
				"drawdown_pct": round(dd * 100, 2),
				"kelly_scale": 1.0,
				"message": f"Minor drawdown: {dd*100:.2f}%",
			}

		elif dd_abs < self.orange:
			kelly_scale = 0.75  # Reduce Kelly by 25%
			return {
				"status": "DRAWDOWN",
				"tier": "yellow",
				"drawdown_pct": round(dd * 100, 2),
				"kelly_scale": kelly_scale,
				"message": f"⚠️ Drawdown: {dd*100:.2f}% — reducing Kelly to {kelly_scale*100:.0f}%",
			}

		elif dd_abs < self.red:
			kelly_scale = 0.50  # Reduce Kelly by 50%
			return {
				"status": "SEVERE_DRAWDOWN",
				"tier": "orange",
				"drawdown_pct": round(dd * 100, 2),
				"kelly_scale": kelly_scale,
				"message": f"⚠️⚠️ Severe drawdown: {dd*100:.2f}% — Kelly at {kelly_scale*100:.0f}%",
			}

		else:
			kelly_scale = 0.25  # Conservative 25% Kelly
			return {
				"status": "CRITICAL_DRAWDOWN",
				"tier": "red",
				"drawdown_pct": round(dd * 100, 2),
				"kelly_scale": kelly_scale,
				"message": f"🛑 CRITICAL: {dd*100:.2f}% drawdown — Kelly capped at {kelly_scale*100:.0f}%",
			}

	def kelly_scale_factor(self) -> float:
		"""Get the Kelly scaling factor based on current drawdown."""
		return self.drawdown_alert()["kelly_scale"]

	def recovery_needed(self) -> dict:
		"""Calculate how much ROI needed to recover."""
		dd = self.drawdown_pct()
		if dd >= 0:
			return {"recovery_needed_pct": 0.0, "message": "No recovery needed"}

		# To recover from X% drawdown, need Y% return
		# If down 10% from $1000 to $900, need to gain 11.1% to get back to $1000
		recovery_pct = abs(dd) / (1 + dd)  # compound interest formula
		recovery_amount = self.peak_bankroll - self.current_bankroll

		return {
			"recovery_needed_pct": round(recovery_pct * 100, 2),
			"recovery_needed_amount": round(recovery_amount, 2),
			"peak_bankroll": round(self.peak_bankroll, 2),
			"current_bankroll": round(self.current_bankroll, 2),
		}
