"""Live odds feeder: pull real matches, feed through analytics, generate signals."""
from __future__ import annotations

import logging
import time
from typing import Optional
from app.core.engine import BettingEngine
from app.data import odds as odds_mod
from app.analytics import spreads, arbitrage, sharp_money
from bot import db

logger = logging.getLogger("tennisboss.odds_feeder")


class LiveOddsFeeder:
	"""Real-time odds fetching and analytics pipeline."""

	def __init__(self, engine: BettingEngine):
		self.engine = engine
		self.sharp_detector = sharp_money.SharpMoneyDetector()
		self.last_fetch = 0
		self.fetch_interval = 60  # seconds between fetches

	def fetch_and_analyze(self, force: bool = False) -> list[dict]:
		"""Fetch live odds, run analytics, return signals.

		Args:
			force: Force fetch even if interval not met

		Returns:
			List of analysis results with edges/signals
		"""
		now = time.time()
		if not force and (now - self.last_fetch) < self.fetch_interval:
			return []

		self.last_fetch = now

		# Fetch upcoming matches (next 48 hours)
		matches = self._get_upcoming_matches()
		if not matches:
			logger.debug("No upcoming matches found")
			return []

		results = []
		for match in matches:
			analysis = self.analyze_single_match(match)
			if analysis:
				results.append(analysis)

		logger.info(f"Analyzed {len(results)} matches, {len([r for r in results if r.get('edge')])} with edges")
		return results

	def analyze_single_match(self, match: dict) -> Optional[dict]:
		"""Analyze single match through full pipeline.

		Returns analysis with EV, arbitrage, sharp signals.
		"""
		try:
			player1 = match.get("player1", "")
			player2 = match.get("player2", "")
			odds1 = match.get("odds1")
			odds2 = match.get("odds2")
			surface = match.get("surface")

			if not (player1 and player2 and odds1 and odds2):
				return None

			# Get model consensus
			engine_result = self.engine.analyze_match(
				player1=player1,
				player2=player2,
				surface=surface,
				odds1=odds1,
				odds2=odds2,
			)

			prob1 = engine_result.get("consensus_prob", 0.5)
			confidence = engine_result.get("confidence", 0.75)

			# Analytics
			spread_s1 = spreads.spread_analysis(prob1, odds1, odds2, confidence)
			arb = arbitrage.check_arbitrage(odds1, odds2)

			# Record snapshot for sharp detection
			match_id = f"{player1}_vs_{player2}".replace(" ", "_")
			self.sharp_detector.record_snapshot(match_id, odds1, volume=match.get("volume", 0))

			sharp_sig = self.sharp_detector.detect_sharp_signal(match_id)

			# Combine into signal
			signal = {
				"match_id": match_id,
				"player1": player1,
				"player2": player2,
				"odds1": odds1,
				"odds2": odds2,
				"surface": surface,
				"model_prob_p1": prob1,
				"confidence": confidence,
				"ev": spread_s1["ev"],
				"recommendation": spread_s1["recommendation"],
				"edge_detected": spread_s1["ev"] > 0.05,
				"arbitrage": arb["is_arb"],
				"arb_pct": arb.get("arb_pct", 0),
				"sharp_signal": sharp_sig.get("is_sharp", False),
				"sharp_confidence": sharp_sig.get("confidence", 0),
				"timestamp": time.time(),
			}

			return signal

		except Exception as e:
			logger.error(f"Error analyzing {match}: {e}")
			return None

	def _get_upcoming_matches(self) -> list[dict]:
		"""Fetch upcoming matches from live odds API.

		This is a placeholder that can be connected to:
		- Odds API (theOddsAPI.com)
		- ESPN API
		- Sports Radar
		- Custom bookmaker feeds
		"""
		# For testing: return mock matches
		try:
			# Try to fetch from Odds API if available
			from app.data import odds_mod
			matches = odds_mod.fetch_upcoming_matches(days=2)
			return matches or self._mock_matches()
		except Exception:
			return self._mock_matches()

	@staticmethod
	def _mock_matches() -> list[dict]:
		"""Return mock matches for testing."""
		return [
			{
				"player1": "Jannik Sinner",
				"player2": "Carlos Alcaraz",
				"odds1": 1.85,
				"odds2": 1.95,
				"surface": "hard",
				"volume": 50000,
			},
			{
				"player1": "Novak Djokovic",
				"player2": "Daniil Medvedev",
				"odds1": 1.75,
				"odds2": 2.10,
				"surface": "hard",
				"volume": 75000,
			},
			{
				"player1": "Iga Swiatek",
				"player2": "Aryna Sabalenka",
				"odds1": 1.95,
				"odds2": 1.85,
				"surface": "clay",
				"volume": 40000,
			},
		]

	def filter_signals(
		self,
		signals: list[dict],
		min_ev: float = 0.05,
		min_confidence: float = 0.60,
	) -> list[dict]:
		"""Filter signals by trading criteria."""
		return [
			s for s in signals
			if s["ev"] >= min_ev
			and s["confidence"] >= min_confidence
		]

	def export_for_trading(self, signals: list[dict]) -> list[dict]:
		"""Format signals for auto-bet engine."""
		return [
			{
				"match_id": s["match_id"],
				"player": s["player1"],
				"model_prob": s["model_prob_p1"],
				"odds": s["odds1"],
				"confidence": s["confidence"],
				"source": "live_odds_feeder",
				"timestamp": s["timestamp"],
			}
			for s in signals
			if s["recommendation"] == "BET"
		]

	def report(self, signals: list[dict]) -> dict:
		"""Generate trading report."""
		edges = [s for s in signals if s["edge_detected"]]
		arbs = [s for s in signals if s["arbitrage"]]
		sharps = [s for s in signals if s["sharp_signal"]]

		return {
			"timestamp": time.time(),
			"total_matches": len(signals),
			"edges_found": len(edges),
			"arbitrage_opportunities": len(arbs),
			"sharp_signals": len(sharps),
			"best_edge": max((s["ev"] for s in edges), default=0),
			"edges": edges,
			"arbs": arbs,
			"sharps": sharps,
		}
