"""Real-time settlement engine: async loop for instant ROI visibility.

Polls live_api.fetch_results every N seconds, records settled matches,
updates ELO, and emits ROI ticks to connected clients via WebSocket/SSE.

Goals:
- Settlement latency < 30 seconds (capture match end → ROI update)
- Minimal API calls (cache + smart polling)
- Live ELO updates for training
- Clear ROI delta visualization
"""
from __future__ import annotations

import asyncio
import datetime as dt
import logging
import time
from typing import Any, Callable, Dict, List, Optional, Set

from . import db, elo, features, live_api, namematch, odds_api, predictor, realtime_alerts, settlement

logger = logging.getLogger("tennisboss.realtime")


class RealtimeSettlementEngine:
    """Async settlement worker for instant ROI feedback."""

    def __init__(
        self,
        mem: Dict[str, Any],
        poll_interval: int = 15,  # seconds between settlement checks
        name_resolver: Optional[Callable[[str], Optional[str]]] = None,
    ):
        self.mem = mem
        self.poll_interval = poll_interval
        # Build name index from known players
        counts = {n: int(p.get("n", 0)) for n, p in mem.get("players", {}).items()}
        self._index = namematch.build_index(list(mem.get("players", {}).keys()), counts)
        # Use the resolver with the built index
        self.resolve = name_resolver or (lambda name: namematch.resolve(name, self._index))
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._last_settled: Dict[str, float] = {}  # event_key -> timestamp
        self._subscribers: List[Callable[[Dict[str, Any]], None]] = []
        self._roi_cache: Dict[str, float] = {}  # settlement_key -> roi_for_match

    def subscribe(self, callback: Callable[[Dict[str, Any]], None]) -> None:
        """Register a callback for settlement ticks."""
        self._subscribers.append(callback)

    async def start(self) -> None:
        """Start the realtime settlement loop."""
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._poll_loop())
        logger.info("Realtime settlement engine started (poll_interval=%ds)", self.poll_interval)

    async def stop(self) -> None:
        """Stop the realtime settlement loop gracefully."""
        self._running = False
        if self._task:
            await self._task
        logger.info("Realtime settlement engine stopped.")

    async def _poll_loop(self) -> None:
        """Main polling loop: fetch results, settle, emit."""
        while self._running:
            try:
                await self._check_and_settle()
            except Exception as e:
                logger.error("Settlement check failed: %s", e)
            await asyncio.sleep(self.poll_interval)

    async def _check_and_settle(self) -> None:
        """Fetch recent results and settle any new matches."""
        cfg = self.mem.get("config", {})
        results = live_api.fetch_results(cfg, days_back=1)
        if not results:
            return

        for r in results:
            ek = r.get("event_key")
            if not ek or r.get("winner") is None:
                continue

            # Skip if already settled or seen too recently
            if db.settled_exists(str(ek)) or ek in self._last_settled:
                continue

            # Attempt to settle this match
            settled = self._settle_match(r)
            if settled:
                self._last_settled[ek] = time.time()
                self._emit("settled", settled)
                logger.info(
                    "Settlement: %s vs %s | pred=%s | correct=%s | roi_delta=%.3f",
                    settled.get("player1"),
                    settled.get("player2"),
                    settled.get("pred_favorite"),
                    settled.get("correct"),
                    settled.get("roi_delta", 0.0),
                )

    def _settle_match(self, r: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Settle one match: predict, record, update ELO, compute ROI delta."""
        ek = r.get("event_key")
        n1 = self.resolve(r["player1"])
        n2 = self.resolve(r["player2"])

        if not n1 or not n2:
            return None

        winner_name = n1 if r["winner"] == "p1" else n2
        pred_fav: Optional[str] = None
        pred_prob1: Optional[float] = None
        correct: Optional[int] = None

        # Predict using current model
        f1 = features.feature_vector(features.get_profile(self.mem, n1))
        f2 = features.feature_vector(features.get_profile(self.mem, n2))
        pr = predictor.predict(self.mem, n1, f1, n2, f2)
        pred_fav = pr["favorite"]
        pred_prob1 = round(predictor.set_to_match_prob(pr["prob1"] / 100.0) * 100, 1)
        if pred_fav:
            correct = 1 if pred_fav == winner_name else 0

        # Record in DB
        settled_rec = {
            "event_key": str(ek),
            "date": r["date"],
            "tour": r.get("tour", ""),
            "tournament": r.get("tournament", ""),
            "player1": n1,
            "player2": n2,
            "winner": winner_name,
            "final_score": r.get("final_score", ""),
            "sets": r.get("sets", []),
            "pred_favorite": pred_fav,
            "pred_prob1": pred_prob1,
            "correct": correct,
        }

        if not db.insert_settled(settled_rec):
            return None

        # Update ELO (continuous learning)
        if "elo" in self.mem:
            mult = elo.dominance_mult(r.get("sets", []), r.get("winner"))
            elo.update(
                self.mem["elo"],
                winner_name,
                n2 if r["winner"] == "p1" else n1,
                mult=mult,
            )

        # Compute ROI delta for this match
        roi_delta = self._compute_roi_delta(settled_rec)

        return {
            "event_key": str(ek),
            "player1": n1,
            "player2": n2,
            "winner": winner_name,
            "pred_favorite": pred_fav,
            "pred_prob1": pred_prob1,
            "correct": correct,
            "score": r.get("final_score", ""),
            "roi_delta": roi_delta,
            "timestamp": time.time(),
        }

    def _compute_roi_delta(self, settled: Dict[str, Any]) -> float:
        """Estimate ROI for this one match if we have odds."""
        bets = {frozenset((b["player1"], b["player2"])): b for b in db.list_bets()}
        b = bets.get(frozenset((settled["player1"], settled["player2"])))
        if not b or b.get("fav_odds") is None:
            return 0.0
        won = settled["winner"] == b["favorite"]
        return (b["fav_odds"] - 1.0) if won else -1.0

    def _emit(self, event_type: str, data: Dict[str, Any]) -> None:
        """Broadcast settlement event to all subscribers."""
        payload = {
            "type": event_type,
            "data": data,
            "ts": time.time(),
        }
        for callback in self._subscribers:
            try:
                callback(payload)
            except Exception as e:
                logger.error("Subscriber callback failed: %s", e)

        # Send alerts (Telegram, Slack, etc.)
        if event_type == "settled":
            alerter = realtime_alerts.get()
            if alerter:
                alerter.on_settlement(payload)


# Global singleton (optional — can also be managed per-app instance)
_ENGINE: Optional[RealtimeSettlementEngine] = None


def init(mem: Dict[str, Any]) -> RealtimeSettlementEngine:
    """Initialize the realtime settlement engine."""
    global _ENGINE
    _ENGINE = RealtimeSettlementEngine(mem, poll_interval=15)
    return _ENGINE


def get() -> Optional[RealtimeSettlementEngine]:
    """Get the global realtime settlement engine."""
    return _ENGINE
