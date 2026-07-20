"""Tennis-data.co.uk nightly ingest + ELO rebuild worker.

Extracted from ``bot/api.py::_data_refresh_loop`` (api.py decomposition Phase 7).

Responsibilities:
- At 02:00 local time, ingest tennis-data.co.uk for current and prior year
- Rebuild ELO ratings in memory when new matches are inserted

Does **not** touch prediction, pick selection, or settlement logic.
"""
from __future__ import annotations

import datetime as dt
import os
import threading
from dataclasses import dataclass
from typing import Any, Dict, Optional

from ..log import log

DEFAULT_STARTUP_DELAY_S = 60
DEFAULT_LOOP_INTERVAL_S = 1800
DEFAULT_REFRESH_HOUR = 2


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        log(f"Worker config: {name}={raw!r} invalide — défaut {default}.", "WARN")
        return default


@dataclass
class DataRefreshCycleState:
    """Mutable state carried across daemon cycles."""

    refreshed_on: str = ""


def refresh_data_once(
    *,
    now: Optional[dt.datetime] = None,
    state: Optional[DataRefreshCycleState] = None,
    refresh_hour: int = DEFAULT_REFRESH_HOUR,
) -> Dict[str, Any]:
    """Run one data refresh check cycle (testable, no sleep).

    Returns summary: ``refreshed``, ``inserted``, ``elo_rebuilt``, ``skipped``, ``reason``.
    """
    from .. import db, elo, memory, tennisdata_feeder

    _now = now or dt.datetime.now()
    _state = state if state is not None else DataRefreshCycleState()
    today = _now.date().isoformat()
    summary: Dict[str, Any] = {
        "refreshed": False,
        "inserted": 0,
        "elo_rebuilt": False,
        "skipped": False,
        "reason": None,
        "refreshed_on": _state.refreshed_on,
    }

    if _now.hour != refresh_hour or _state.refreshed_on == today:
        summary["skipped"] = True
        summary["reason"] = (
            "already_refreshed_today"
            if _state.refreshed_on == today
            else "not_refresh_hour"
        )
        return summary

    log("Data refresh: ingest tennis-data.co.uk...")
    result = tennisdata_feeder.ingest(years=[_now.year, _now.year - 1])
    inserted = int(result.get("inserted", 0))
    log(f"Data refresh: {inserted} nouveaux matchs.")
    summary["inserted"] = inserted

    if inserted > 0:
        rows = db.all_matches_chrono()
        elo_r: Dict[str, float] = {}
        for row in rows:
            row_d = dict(row)
            elo.update(elo_r, row_d.get("winner"), row_d.get("loser"))
        mem = memory.load()
        mem["elo"] = elo_r
        memory.save(mem)
        log(f"ELO rebuild: {len(elo_r)} joueurs.")
        summary["elo_rebuilt"] = True

    _state.refreshed_on = today
    summary["refreshed"] = True
    summary["refreshed_on"] = today
    return summary


def run_loop(
    *,
    startup_delay: Optional[int] = None,
    interval: Optional[int] = None,
    refresh_hour: Optional[int] = None,
    stop_event: Optional[threading.Event] = None,
    state: Optional[DataRefreshCycleState] = None,
) -> None:
    """Daemon loop: check for nightly data refresh until ``stop_event`` is set."""
    _startup = startup_delay if startup_delay is not None else _env_int(
        "DATA_REFRESH_STARTUP_DELAY_S", DEFAULT_STARTUP_DELAY_S,
    )
    _interval = interval if interval is not None else _env_int(
        "DATA_REFRESH_INTERVAL_S", DEFAULT_LOOP_INTERVAL_S,
    )
    _refresh_hour = refresh_hour if refresh_hour is not None else _env_int(
        "DATA_REFRESH_HOUR", DEFAULT_REFRESH_HOUR,
    )
    _stop = stop_event or threading.Event()
    _state = state if state is not None else DataRefreshCycleState()

    if _startup > 0:
        if _stop.wait(_startup):
            return

    log(
        f"Data refresh worker démarré (intervalle {_interval}s, "
        f"heure cible {_refresh_hour}h).",
    )

    while not _stop.is_set():
        try:
            refresh_data_once(state=_state, refresh_hour=_refresh_hour)
        except Exception as exc:  # noqa: BLE001 — worker must survive cycle errors
            log(f"Data refresh erreur: {exc}", "WARN")
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
        name="data-refresh-worker",
    )
    thread.start()
    return thread
