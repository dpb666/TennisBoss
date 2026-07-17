"""Watchlist (followed matches) odds refresh worker.

Extracted from ``bot/api.py::_followed_matches_refresh_loop`` as Phase 1 of the
api.py decomposition (see docs/ARCHITECTURE_BLUEPRINT.md §5.3, docs/API_DECOMPOSITION.md).

Responsibilities:
- Poll ``db.list_followed_matches()`` on a fixed interval
- Fetch fresh match-winner odds (shorter TTL for live events)
- Persist snapshots and fire steam alerts when line moves ≥ threshold

Does **not** touch prediction, pick selection, or settlement logic.
"""
from __future__ import annotations

import os
import threading
import time
from typing import Any, Dict, Optional

from ..log import log

# Defaults match pre-extraction behaviour in api.py (Jul 2026).
DEFAULT_STARTUP_DELAY_S = 45
DEFAULT_LOOP_INTERVAL_S = 60
DEFAULT_LIVE_TTL_S = 30
DEFAULT_PREMATCH_TTL_S = 60
ODDS_MOVE_THRESHOLD = 0.03


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        log(f"Worker config: {name}={raw!r} invalide — défaut {default}.", "WARN")
        return default


def refresh_watchlist_once(
    *,
    live_ttl: int = DEFAULT_LIVE_TTL_S,
    prematch_ttl: int = DEFAULT_PREMATCH_TTL_S,
    odds_move_threshold: float = ODDS_MOVE_THRESHOLD,
) -> Dict[str, Any]:
    """Run a single watchlist refresh cycle (testable, no sleep).

    Returns a summary dict: ``watched``, ``refreshed``, ``skipped``, ``reason``.
    """
    from .. import db, odds_api
    from .. import realtime_alerts as realtime_alerts_mod

    watched = db.list_followed_matches()
    summary: Dict[str, Any] = {
        "watched": len(watched),
        "refreshed": 0,
        "skipped": False,
        "reason": None,
    }

    if not watched:
        summary["skipped"] = True
        summary["reason"] = "empty_watchlist"
        return summary

    if not odds_api.is_enabled() or not odds_api._current_key():
        summary["skipped"] = True
        summary["reason"] = "odds_api_unavailable"
        return summary

    all_events = odds_api.fetch_tennis_events(upcoming_only=False)
    idx = odds_api.build_event_index(all_events)
    refreshed = 0

    for row in watched:
        p1, p2 = row["player1"], row["player2"]
        ev = odds_api.find_event(idx, p1, p2)
        if not ev:
            continue

        eid = ev.get("id") or row["event_key"]
        is_live = ev.get("status") in {"live", "inplay"}
        ttl = live_ttl if is_live else prematch_ttl
        mw = odds_api.fetch_match_winner(eid, ttl=ttl)
        if not mw:
            continue

        home_odds = float(mw["home_odds"])
        away_odds = float(mw["away_odds"])
        prev_h = row["last_odds_home"]
        prev_a = row["last_odds_away"]
        db.update_followed_match_odds(str(eid), home_odds, away_odds)
        db.record_market_snapshot(str(eid), p1, p2, home_odds, away_odds)

        if prev_h and prev_h > 1.0 and abs(home_odds - prev_h) / prev_h >= odds_move_threshold:
            realtime_alerts_mod.on_odds_move(p1, p2, p1, float(prev_h), home_odds)
        if prev_a and prev_a > 1.0 and abs(away_odds - prev_a) / prev_a >= odds_move_threshold:
            realtime_alerts_mod.on_odds_move(p1, p2, p2, float(prev_a), away_odds)

        refreshed += 1

    summary["refreshed"] = refreshed
    if refreshed:
        log(f"Watchlist: {refreshed}/{len(watched)} match(s) odds MAJ.")
    return summary


def run_loop(
    *,
    startup_delay: Optional[int] = None,
    interval: Optional[int] = None,
    stop_event: Optional[threading.Event] = None,
) -> None:
    """Daemon loop: refresh followed-match odds until ``stop_event`` is set."""
    _startup = startup_delay if startup_delay is not None else _env_int(
        "MATCH_REFRESH_STARTUP_DELAY_S", DEFAULT_STARTUP_DELAY_S,
    )
    _interval = interval if interval is not None else _env_int(
        "MATCH_REFRESH_INTERVAL_S", DEFAULT_LOOP_INTERVAL_S,
    )
    _stop = stop_event or threading.Event()

    if _startup > 0:
        if _stop.wait(_startup):
            return

    log(
        f"Match refresh worker démarré (intervalle {_interval}s, "
        f"TTL live={DEFAULT_LIVE_TTL_S}s).",
    )

    while not _stop.is_set():
        try:
            refresh_watchlist_once()
        except Exception as exc:  # noqa: BLE001 — worker must survive cycle errors
            log(f"Watchlist refresh échoué ({exc}).", "WARN")
        if _stop.wait(_interval):
            break


def start_daemon_thread(
    *,
    startup_delay: Optional[int] = None,
    interval: Optional[int] = None,
) -> threading.Thread:
    """Start the worker in a daemon thread (used by ``api.serve()``)."""
    thread = threading.Thread(
        target=run_loop,
        kwargs={"startup_delay": startup_delay, "interval": interval},
        daemon=True,
        name="match-refresh-worker",
    )
    thread.start()
    return thread
