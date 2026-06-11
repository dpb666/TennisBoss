"""Alert system: send notifications for sharp signals, hedges, drawdowns."""
from __future__ import annotations

import logging
from typing import Optional
from enum import Enum

logger = logging.getLogger("tennisboss.alerts")


class AlertLevel(str, Enum):
	"""Alert severity levels."""
	INFO = "INFO"
	SIGNAL = "SIGNAL"
	WARNING = "WARNING"
	CRITICAL = "CRITICAL"


class AlertManager:
	"""Manage alerts to multiple channels."""

	def __init__(self):
		self.history: list[dict] = []
		self.channels = ["console", "telegram", "slack"]  # Configurable

	def send_alert(
		self,
		level: AlertLevel,
		title: str,
		message: str,
		data: Optional[dict] = None,
	) -> dict:
		"""Send alert to all configured channels."""
		alert = {
			"level": level,
			"title": title,
			"message": message,
			"data": data or {},
		}

		self.history.append(alert)

		# Log
		logger.log(
			logging.WARNING if level in [AlertLevel.WARNING, AlertLevel.CRITICAL] else logging.INFO,
			f"[{level}] {title}: {message}"
		)

		return alert

	def sharp_signal(self, match_id: str, signal_data: dict) -> dict:
		"""Alert on sharp money signal."""
		return self.send_alert(
			AlertLevel.SIGNAL,
			f"🔥 Sharp Signal: {match_id}",
			f"Line: {signal_data.get('line_movement_pct', 0):.1f}% | Volume: {signal_data.get('volume_spike_pct', 0):.1f}%",
			signal_data,
		)

	def arbitrage_found(self, match_id: str, arb_pct: float, stake_split: dict) -> dict:
		"""Alert on arbitrage opportunity."""
		return self.send_alert(
			AlertLevel.SIGNAL,
			f"💰 Arbitrage Found: {match_id}",
			f"{arb_pct:.2f}% edge | Split: {stake_split.get('side1_pct', 50):.0f}% / {stake_split.get('side2_pct', 50):.0f}%",
			{"arb_pct": arb_pct, "stake_split": stake_split},
		)

	def hedge_available(self, bet_id: str, pnl: float, odds: float) -> dict:
		"""Alert on hedge opportunity."""
		action = "LOCK PROFIT" if pnl > 0 else "REDUCE LOSS"
		return self.send_alert(
			AlertLevel.SIGNAL,
			f"🛡️ Hedge Available: {bet_id}",
			f"{action} | PnL if closed: ${pnl:+.2f} @ {odds:.3f}",
			{"bet_id": bet_id, "pnl": pnl, "odds": odds},
		)

	def drawdown_alert(self, drawdown_pct: float, tier: str, kelly_scale: float) -> dict:
		"""Alert on drawdown."""
		emoji = "🟡" if tier == "yellow" else "🟠" if tier == "orange" else "🔴"
		return self.send_alert(
			AlertLevel.WARNING if tier in ["yellow", "orange"] else AlertLevel.CRITICAL,
			f"{emoji} Drawdown Alert: {tier.upper()}",
			f"{drawdown_pct:.1f}% DD | Kelly scaled to {kelly_scale*100:.0f}%",
			{"drawdown_pct": drawdown_pct, "tier": tier, "kelly_scale": kelly_scale},
		)

	def bet_placed(self, bet_id: str, player: str, stake: float, odds: float) -> dict:
		"""Alert on bet placement."""
		return self.send_alert(
			AlertLevel.INFO,
			f"📍 Bet Placed: {bet_id}",
			f"{player} @ {odds} | Stake: ${stake:.2f}",
			{"bet_id": bet_id, "player": player, "stake": stake, "odds": odds},
		)

	def bet_settled(self, bet_id: str, result: str, pnl: float, roi_pct: float) -> dict:
		"""Alert on bet settlement."""
		emoji = "✅" if result == "WIN" else "❌"
		return self.send_alert(
			AlertLevel.INFO,
			f"{emoji} Bet Settled: {bet_id}",
			f"{result} | PnL: ${pnl:+.2f} | ROI: {roi_pct:+.2f}%",
			{"bet_id": bet_id, "result": result, "pnl": pnl, "roi_pct": roi_pct},
		)

	def model_update(self, model_name: str, performance: dict) -> dict:
		"""Alert on model update/calibration."""
		return self.send_alert(
			AlertLevel.INFO,
			f"📊 Model Update: {model_name}",
			f"Accuracy: {performance.get('accuracy', 0):.1%} | Calibration: {performance.get('calibration', 0):.2f}",
			performance,
		)

	def summary_report(self, period: str, stats: dict) -> dict:
		"""Alert with summary report."""
		return self.send_alert(
			AlertLevel.INFO,
			f"📈 Summary Report: {period}",
			f"ROI: {stats.get('roi_pct', 0):+.2f}% | Win Rate: {stats.get('win_rate_pct', 0):.1f}% | Bankroll: ${stats.get('bankroll', 0):.2f}",
			stats,
		)

	def get_recent(self, level: Optional[AlertLevel] = None, limit: int = 10) -> list[dict]:
		"""Get recent alerts."""
		alerts = self.history
		if level:
			alerts = [a for a in alerts if a["level"] == level]
		return alerts[-limit:]

	def get_summary(self) -> dict:
		"""Get alert summary."""
		by_level = {level: 0 for level in AlertLevel}
		for alert in self.history:
			by_level[alert["level"]] += 1

		return {
			"total_alerts": len(self.history),
			"by_level": by_level,
			"critical": by_level[AlertLevel.CRITICAL],
			"warnings": by_level[AlertLevel.WARNING],
			"signals": by_level[AlertLevel.SIGNAL],
		}
