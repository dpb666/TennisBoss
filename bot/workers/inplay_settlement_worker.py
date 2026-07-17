"""Inplay picks auto-settlement worker.

Extracted from ``bot/api.py::_inplay_settle_loop`` (api.py decomposition Phase 2).

Responsibilities:
- Poll pending inplay picks (`db.list_inplay_picks_pending`)
- Compare against live event IDs from odds API
- Auto-settle finished matches via `db.auto_settle_picks`

Does **not** touch value-pick settlement, calibration refit, or prediction logic.
"""
from __future__ import annotations

import os
import threading
from typing import Any, Dict, List, Optional

from ..log import log

DEFAULT_LOOP_INTERVAL_S = 300


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        log(f"Worker config: {name}={raw!r} invalide — défaut {default}.", "WARN")
        return default


def settle_inplay_once() -> Dict[str, Any]:
    """Run one inplay settlement cycle (testable, no sleep).

    Returns summary: ``pending``, ``settled``, ``settled_rows``, ``skipped``, ``reason``.
    """
    from .. import db, odds_api

    pending = db.list_inplay_picks_pending()
    summary: Dict[str, Any] = {
        "pending": len(pending),
        "settled": 0,
        "settled_rows": [],
        "skipped": False,
        "reason": None,
    }

    if not pending:
        summary["skipped"] = True
        summary["reason"] = "no_pending_picks"
        return summary

    try:
        live_events = odds_api.fetch_live_events()
        live_ids = {str(e.get("event_id", "")) for e in live_events}
    except Exception as exc:  # noqa: BLE001
        log(
            f"fetch_live_events échoué (inplay settle worker) ({exc}) "
            "— traité comme aucun match live.",
            "WARN",
        )
        live_ids = set()

    settled: List[Dict[str, Any]] = db.auto_settle_picks(live_ids)
    summary["settled"] = len(settled)
    summary["settled_rows"] = settled

    if settled:
        log(
            f"[Inplay] Auto-settled {len(settled)} pick(s): "
            f"{[(s['pick'], s['result'], s['pnl']) for s in settled]}",
            "INFO",
        )
    return summary


def run_loop(
    *,
    interval: Optional[int] = None,
    stop_event: Optional[threading.Event] = None,
) -> None:
    """Daemon loop: settle inplay picks every ``interval`` seconds.

    Matches pre-extraction behaviour: sleep *before* each cycle (including the first).
    """
    _interval = interval if interval is not None else _env_int(
        "INPLAY_SETTLE_INTERVAL_S", DEFAULT_LOOP_INTERVAL_S,
    )
    _stop = stop_event or threading.Event()

    log(f"Inplay settlement worker démarré (intervalle {_interval}s).")

    while not _stop.is_set():
        if _stop.wait(_interval):
            break
        try:
            settle_inplay_once()
        except Exception as exc:  # noqa: BLE001
            log(f"[Inplay] Erreur settlement: {exc}", "WARN")


def start_daemon_thread(*, interval: Optional[int] = None) -> threading.Thread:
    """Start the worker in a daemon thread (used by ``api.serve()``)."""
    thread = threading.Thread(
        target=run_loop,
        kwargs={"interval": interval},
        daemon=True,
        name="inplay-settlement-worker",
    )
    thread.start()
    return thread
