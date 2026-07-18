"""CLV closing snapshot and live CLV settlement worker.

Extracted from ``bot/api.py::_clv_closing_loop`` (api.py decomposition Phase 3).

Responsibilities:
- Snapshot pre-match closing odds (sharp book) for open CLV picks
- Fast-settle CLV picks when live scores show match finished
- Fire steam alerts on meaningful line moves vs pick odds

Does **not** touch value-pick settlement, calibration refit, or prediction logic.
"""
from __future__ import annotations

import os
import threading
from typing import Any, Dict, List, Optional, Set

from ..log import log

LIVE_STATUSES: Set[str] = {"live", "inplay"}
DEFAULT_STARTUP_DELAY_S = 30
DEFAULT_LOOP_INTERVAL_S = 600
# Closing odds TTL : plus court que TTL_ODDS (10min) pour capturer le drift pré-match.
CLV_ODDS_TTL_S = 120


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        log(f"Worker config: {name}={raw!r} invalide — défaut {default}.", "WARN")
        return default


def _sets_target(h_sets: int, a_sets: int) -> int:
    """Best-of-3 ends at 2 sets; best-of-5 at 3."""
    return 3 if max(h_sets, a_sets) >= 3 else 2


def _find_event_for_pick(
    pick: Dict[str, Any],
    prematch_idx: Dict[frozenset, Dict[str, Any]],
    live_idx: Dict[frozenset, Dict[str, Any]],
    all_events: List[Dict[str, Any]],
) -> tuple[Optional[Dict[str, Any]], str]:
    """Resolve odds-api event for a CLV pick.

    Prefer ``event_key`` (odds-api id stored at seed time) — name matching
    alone failed silently when player name formats diverged (~Jul 2026),
    leaving closing_odds NULL until settle's last_seen fallback (CLV=0).
    """
    from .. import odds_api

    event_key = str(pick.get("event_key") or "").strip()
    if event_key:
        for ev in all_events:
            if str(ev.get("id") or "") == event_key:
                return ev, "id"

    p1 = pick["player1"]
    p2 = pick["player2"]
    lev = odds_api.find_event(live_idx, p1, p2)
    if lev:
        return lev, "name"
    ev = odds_api.find_event(prematch_idx, p1, p2)
    if ev:
        return ev, "name"
    return None, ""


def refresh_clv_once() -> Dict[str, Any]:
    """Run one CLV closing / live-settle cycle (testable, no sleep)."""
    from .. import clv, db, odds_api
    from .. import realtime_alerts as realtime_alerts_mod

    open_picks = db.list_clv_open()
    summary: Dict[str, Any] = {
        "open_picks": len(open_picks),
        "closing_updated": 0,
        "settled_live": 0,
        "matched_by_id": 0,
        "matched_by_name": 0,
        "event_not_found": 0,
        "skipped": False,
        "reason": None,
    }

    if not open_picks:
        summary["skipped"] = True
        summary["reason"] = "no_open_clv_picks"
        return summary

    if not odds_api.is_enabled() or not odds_api._current_key():
        summary["skipped"] = True
        summary["reason"] = "odds_api_unavailable"
        return summary

    all_events = odds_api.fetch_tennis_events(upcoming_only=True)
    prematch = [e for e in all_events if e.get("status") not in LIVE_STATUSES]
    idx = odds_api.build_event_index(prematch)
    live_evs = [e for e in all_events if e.get("status") in LIVE_STATUSES]
    idx_live = odds_api.build_event_index(live_evs)

    updated = 0
    settled_live = 0

    for pick in open_picks:
        p1 = pick["player1"]
        p2 = pick["player2"]
        pick_side = pick["pick_side"]

        ev, match_method = _find_event_for_pick(pick, idx, idx_live, all_events)
        if not ev:
            summary["event_not_found"] += 1
            continue
        if match_method == "id":
            summary["matched_by_id"] += 1
        elif match_method == "name":
            summary["matched_by_name"] += 1

        if ev.get("status") in LIVE_STATUSES:
            scores = ev.get("scores") or {}
            try:
                h_sets = int(scores.get("home", 0))
                a_sets = int(scores.get("away", 0))
            except (TypeError, ValueError):
                h_sets = a_sets = 0
            target = _sets_target(h_sets, a_sets)
            if h_sets >= target or a_sets >= target:
                live_winner = ev.get("home") if h_sets > a_sets else ev.get("away")
                if live_winner:
                    try:
                        clv.settle(p1, p2, live_winner)
                        log(
                            f"CLV live-settle: {p1} vs {p2} → {live_winner} "
                            f"({h_sets}-{a_sets})",
                        )
                        settled_live += 1
                    except Exception as exc:  # noqa: BLE001
                        log(f"CLV live-settle erreur: {exc}", "WARN")
            continue

        mw = odds_api.fetch_match_winner(ev["id"], ttl=CLV_ODDS_TTL_S)
        if not mw:
            continue
        curr_odds = mw["home_odds"] if pick_side == p1 else mw["away_odds"]
        mw_sharp = odds_api.fetch_match_winner(
            ev["id"], bookmakers=odds_api._sharp_book(), ttl=CLV_ODDS_TTL_S,
        )
        if mw_sharp:
            sharp_h = mw_sharp["home_odds"]
            sharp_a = mw_sharp["away_odds"]
        else:
            sharp_h, sharp_a = mw["home_odds"], mw["away_odds"]
        clv.refresh_closing(
            pick["event_key"],
            pick_side,
            p1,
            sharp_h,
            sharp_a,
            match_date=ev.get("date") or ev.get("commence_time") or "",
        )
        pick_odds_orig = float(pick["pick_odds"] or 0)
        if pick_odds_orig > 1.0 and curr_odds > 1.0:
            realtime_alerts_mod.on_odds_move(p1, p2, pick_side, pick_odds_orig, curr_odds)
        updated += 1

    summary["closing_updated"] = updated
    summary["settled_live"] = settled_live

    parts: List[str] = []
    if updated:
        parts.append(f"{updated} closing MAJ")
    if settled_live:
        parts.append(f"{settled_live} settled live")
    if parts:
        log(f"CLV: {', '.join(parts)}.")
    return summary


def run_loop(
    *,
    startup_delay: Optional[int] = None,
    interval: Optional[int] = None,
    stop_event: Optional[threading.Event] = None,
) -> None:
    """Daemon loop: CLV closing refresh until ``stop_event`` is set."""
    _startup = startup_delay if startup_delay is not None else _env_int(
        "CLV_CLOSING_STARTUP_DELAY_S", DEFAULT_STARTUP_DELAY_S,
    )
    _interval = interval if interval is not None else _env_int(
        "CLV_CLOSING_INTERVAL_S", DEFAULT_LOOP_INTERVAL_S,
    )
    _stop = stop_event or threading.Event()

    if _startup > 0:
        if _stop.wait(_startup):
            return

    log(f"CLV closing worker démarré (intervalle {_interval}s).")

    while not _stop.is_set():
        try:
            refresh_clv_once()
        except Exception as exc:  # noqa: BLE001
            log(f"CLV closing loop erreur: {exc}", "WARN")
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
        name="clv-closing-worker",
    )
    thread.start()
    return thread
