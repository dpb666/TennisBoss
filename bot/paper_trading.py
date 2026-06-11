"""Paper trading: simulate bets with auto-bet engine + position tracking."""
from __future__ import annotations

import logging
import time
import uuid
from typing import Optional
from app.trading import auto_bet_engine, kelly_dynamic, position_tracker, hedge_manager
from app.risk import drawdown_alerts

logger = logging.getLogger("tennisboss.paper_trading")


class PaperTradingSession:
	"""Paper trading simulator with full risk management."""

	def __init__(
		self,
		starting_bankroll: float = 1000,
		min_ev: float = 0.05,
		min_confidence: float = 0.60,
		kelly_fraction: float = 0.25,
	):
		self.bankroll = starting_bankroll
		self.starting_bankroll = starting_bankroll
		self.min_ev = min_ev
		self.min_confidence = min_confidence
		self.kelly_fraction = kelly_fraction

		# Engines
		self.auto_bet = auto_bet_engine.AutoBetEngine(
			min_ev=min_ev,
			min_confidence=min_confidence,
		)
		self.positions = position_tracker.PositionTracker()
		self.hedges = hedge_manager.HedgeManager()
		self.drawdown = drawdown_alerts.DrawdownAlerts(peak_bankroll=starting_bankroll)

		# History
		self.trades: list[dict] = []
		self.settlements: list[dict] = []

	def place_bet(
		self,
		match_id: str,
		player: str,
		model_prob: float,
		odds: float,
		confidence: float,
	) -> dict:
		"""Place a paper bet (no real money)."""
		# Auto-bet approval
		should_bet, reason, stake_pct = self.auto_bet.should_place_bet(
			model_prob, odds, confidence
		)

		if not should_bet:
			return {
				"match_id": match_id,
				"status": "REJECTED",
				"reason": reason,
			}

		# Dynamic Kelly sizing with risk adjustments
		kelly_result = kelly_dynamic.composite_kelly(
			prob=model_prob,
			odds=odds,
			confidence=confidence,
			portfolio_volatility=self._calc_portfolio_vol(),
			current_drawdown_pct=self.drawdown.drawdown_pct() * 100,
			kelly_pct=self.kelly_fraction,
		)

		stake = self.bankroll * kelly_result["final_kelly_fraction"]
		stake = max(1, min(stake, self.bankroll * 0.05))  # Clamp: 1-5% of bankroll

		# Record position
		bet_id = str(uuid.uuid4())[:8]
		self.positions.open_position(
			bet_id=bet_id,
			match_id=match_id,
			player=player,
			stake=stake,
			odds=odds,
			model_prob=model_prob,
			confidence=confidence,
		)

		# Log trade
		trade = {
			"bet_id": bet_id,
			"match_id": match_id,
			"player": player,
			"stake": stake,
			"odds": odds,
			"model_prob": model_prob,
			"confidence": confidence,
			"timestamp": time.time(),
			"kelly_details": kelly_result,
			"status": "OPEN",
		}
		self.trades.append(trade)

		logger.info(f"[PAPER] Bet placed: {bet_id} {player} @{odds} stake=${stake:.2f}")

		return {
			"bet_id": bet_id,
			"match_id": match_id,
			"status": "APPROVED",
			"stake": stake,
			"reason": reason,
			"kelly_pct": kelly_result["final_stake_pct"],
		}

	def settle_bet(
		self,
		bet_id: str,
		result: bool,  # True = won, False = lost
		actual_odds: Optional[float] = None,
	) -> dict:
		"""Settle a paper bet."""
		# Close position
		pos = self.positions.close_position(bet_id, result)

		if not pos:
			return {"error": f"Bet {bet_id} not found"}

		# Update bankroll
		pnl = pos["final_pnl"]
		self.bankroll += pnl
		self.drawdown.update_bankroll(self.bankroll)

		# Log settlement
		settlement = {
			"bet_id": bet_id,
			"result": "WIN" if result else "LOSS",
			"stake": pos["stake"],
			"pnl": pnl,
			"odds": pos["odds"],
			"bankroll_after": self.bankroll,
			"timestamp": time.time(),
		}
		self.settlements.append(settlement)

		logger.info(f"[PAPER] Bet settled: {bet_id} {settlement['result']} PnL=${pnl:+.2f}")

		return settlement

	def check_hedges(self) -> list[dict]:
		"""Check all open positions for hedge opportunities."""
		open_pos = self.positions.get_open_positions()
		hedges = []

		for pos in open_pos:
			# Simulate odds movement (±5% random)
			import random
			current_odds = pos["odds"] * (1 + random.uniform(-0.05, 0.05))

			hedge = self.hedges.calculate_hedge(
				pos["stake"],
				pos["odds"],
				current_odds,
			)

			if hedge["hedge"]["pnl_if_closed"] > 0:
				hedges.append({
					"bet_id": pos["bet_id"],
					"match_id": pos["match_id"],
					**hedge,
				})

		return hedges

	def _calc_portfolio_vol(self) -> float:
		"""Calculate portfolio volatility from recent settlements."""
		if len(self.settlements) < 5:
			return 0.02  # Default 2%

		recent = self.settlements[-20:]
		pnls = [s["pnl"] for s in recent]

		if not pnls:
			return 0.02

		mean_pnl = sum(pnls) / len(pnls)
		variance = sum((p - mean_pnl) ** 2 for p in pnls) / len(pnls)
		vol = (variance ** 0.5) / self.bankroll

		return max(0.01, min(vol, 0.10))  # Clamp: 1-10%

	def status(self) -> dict:
		"""Get session status."""
		summary = self.positions.summary()
		dd_alert = self.drawdown.drawdown_alert()

		total_pnl = self.bankroll - self.starting_bankroll
		roi = (total_pnl / self.starting_bankroll) * 100

		return {
			"bankroll": round(self.bankroll, 2),
			"starting": round(self.starting_bankroll, 2),
			"total_pnl": round(total_pnl, 2),
			"roi_pct": round(roi, 2),
			"open_bets": summary["open_positions"],
			"settled": summary["settled"],
			"drawdown": {
				"current_pct": round(self.drawdown.drawdown_pct() * 100, 2),
				"tier": dd_alert["tier"],
				"kelly_scale": dd_alert["kelly_scale"],
			},
			"recent_trades": self.trades[-5:] if self.trades else [],
		}

	def report(self) -> dict:
		"""Generate trading report."""
		if not self.settlements:
			return {"error": "No settled bets yet"}

		wins = [s for s in self.settlements if s["result"] == "WIN"]
		losses = [s for s in self.settlements if s["result"] == "LOSS"]

		win_rate = len(wins) / len(self.settlements) if self.settlements else 0
		avg_win = sum(s["pnl"] for s in wins) / len(wins) if wins else 0
		avg_loss = sum(s["pnl"] for s in losses) / len(losses) if losses else 0

		total_pnl = self.bankroll - self.starting_bankroll

		return {
			"total_bets": len(self.settlements),
			"wins": len(wins),
			"losses": len(losses),
			"win_rate_pct": round(win_rate * 100, 1),
			"avg_win": round(avg_win, 2),
			"avg_loss": round(avg_loss, 2),
			"win_loss_ratio": round(avg_win / abs(avg_loss), 2) if avg_loss != 0 else 0,
			"total_pnl": round(total_pnl, 2),
			"roi_pct": round((total_pnl / self.starting_bankroll) * 100, 2),
			"bankroll": round(self.bankroll, 2),
			"kelly_scale": self.drawdown.kelly_scale_factor(),
		}
