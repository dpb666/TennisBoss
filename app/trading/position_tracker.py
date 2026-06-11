"""Position tracker: track open bets, exposure, P&L."""
from __future__ import annotations

import time
from typing import Optional


class PositionTracker:
	"""Track all open betting positions."""

	def __init__(self):
		self.positions: dict[str, dict] = {}  # bet_id -> position data
		self.match_id_map: dict[str, list[str]] = {}  # match_id -> [bet_ids]

	def open_position(
		self,
		bet_id: str,
		match_id: str,
		player: str,
		stake: float,
		odds: float,
		model_prob: float,
		confidence: float,
		timestamp: Optional[float] = None,
	) -> dict:
		"""Record an open position."""
		ts = timestamp or time.time()

		position = {
			"bet_id": bet_id,
			"match_id": match_id,
			"player": player,
			"stake": stake,
			"odds": odds,
			"model_prob": model_prob,
			"confidence": confidence,
			"opened_at": ts,
			"status": "OPEN",
			"current_pnl": 0.0,  # Updated as live odds change
			"if_win": stake * (odds - 1),
			"if_loss": -stake,
		}

		self.positions[bet_id] = position

		if match_id not in self.match_id_map:
			self.match_id_map[match_id] = []
		self.match_id_map[match_id].append(bet_id)

		return position

	def update_live_pnl(
		self,
		bet_id: str,
		current_odds: float,
	) -> Optional[float]:
		"""Update P&L if odds change before match (for hedging)."""
		if bet_id not in self.positions:
			return None

		pos = self.positions[bet_id]
		original_odds = pos["odds"]
		stake = pos["stake"]

		# Simplified: if backing at original odds, closing at current odds
		if current_odds > original_odds:
			# Favorable movement: could lock in profit by laying
			pnl = stake * (current_odds - original_odds)
		else:
			# Adverse movement: potential loss if closed now
			pnl = -stake * (original_odds - current_odds)

		pos["current_pnl"] = pnl
		pos["current_odds"] = current_odds

		return pnl

	def close_position(
		self,
		bet_id: str,
		result: bool,  # True = won, False = lost
		timestamp: Optional[float] = None,
	) -> Optional[dict]:
		"""Close a position after settlement."""
		if bet_id not in self.positions:
			return None

		pos = self.positions[bet_id]
		ts = timestamp or time.time()

		pnl = pos["if_win"] if result else pos["if_loss"]

		pos["status"] = "SETTLED"
		pos["result"] = "WIN" if result else "LOSS"
		pos["final_pnl"] = pnl
		pos["closed_at"] = ts

		return pos

	def get_open_positions(self) -> list[dict]:
		"""Get all currently open positions."""
		return [p for p in self.positions.values() if p["status"] == "OPEN"]

	def get_positions_by_match(self, match_id: str) -> list[dict]:
		"""Get all positions for a match."""
		bet_ids = self.match_id_map.get(match_id, [])
		return [self.positions[bid] for bid in bet_ids if bid in self.positions]

	def portfolio_exposure(self) -> dict:
		"""Calculate total portfolio exposure."""
		open_pos = self.get_open_positions()

		total_stake = sum(p["stake"] for p in open_pos)
		potential_win = sum(p["if_win"] for p in open_pos)
		potential_loss = sum(p["if_loss"] for p in open_pos)

		return {
			"num_open": len(open_pos),
			"total_stake": round(total_stake, 2),
			"potential_win": round(potential_win, 2),
			"potential_loss": round(abs(potential_loss), 2),
			"max_loss_pct": round(abs(potential_loss) / total_stake * 100, 1) if total_stake > 0 else 0,
		}

	def correlation_check(
		self,
		new_position_player: str,
		match_ids_to_check: list[str],
	) -> dict:
		"""Check if new position correlates with existing exposure."""
		open_pos = self.get_open_positions()

		# Find matches this player appears in
		player_matches = set()
		for pos in open_pos:
			if new_position_player in pos["player"].lower():
				player_matches.add(pos["match_id"])

		correlated_positions = [
			p for p in open_pos
			if p["match_id"] in player_matches
		]

		correlated_exposure = sum(p["stake"] for p in correlated_positions)

		return {
			"new_player": new_position_player,
			"correlated_positions": len(correlated_positions),
			"correlated_stake": round(correlated_exposure, 2),
			"is_high_correlation": len(correlated_positions) > 0,
		}

	def summary(self) -> dict:
		"""Get portfolio summary."""
		open_pos = self.get_open_positions()
		exposure = self.portfolio_exposure()

		settled = [p for p in self.positions.values() if p["status"] == "SETTLED"]
		wins = [p for p in settled if p.get("result") == "WIN"]
		losses = [p for p in settled if p.get("result") == "LOSS"]

		total_pnl = sum(p.get("final_pnl", 0) for p in settled)

		return {
			"open_positions": exposure["num_open"],
			"total_stake": exposure["total_stake"],
			"exposure": exposure,
			"settled": {
				"total": len(settled),
				"wins": len(wins),
				"losses": len(losses),
				"win_rate": round(len(wins) / len(settled) * 100, 1) if settled else 0,
				"total_pnl": round(total_pnl, 2),
			},
		}
