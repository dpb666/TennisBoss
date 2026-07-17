"""Value-picks auto-settlement worker.

Extracted from ``bot/api.py::_settlement_loop`` (api.py decomposition Phase 4).

Runs ``settlement.run_settlement``, optional calibration refit (via injected
callback — lives in api.py), mistake-learner refresh, and stale-pick voiding.

Does **not** implement settlement math or modify frozen predictor thresholds.
"""
from __future__ import annotations

import datetime as dt
import os
import threading
from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional

from ..log import log

DEFAULT_LOOP_INTERVAL_S = 600
DEFAULT_DAYS_BACK = 2
STALE_VOID_HOURS = 48


@dataclass(frozen=True)
class SettlementDeps:
    """Runtime dependencies injected from ``bot.api`` (avoids import cycles)."""

    get_mem: Callable[[], Dict[str, Any]]
    resolve: Callable[[str], Optional[str]]
    refit_calibration: Callable[[], Dict[str, Any]]
    get_calib_k: Callable[[], float]


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        log(f"Worker config: {name}={raw!r} invalide — défaut {default}.", "WARN")
        return default


def _snapshot_open_value_picks() -> Dict[int, Dict[str, Any]]:
    from .. import db

    with db.connect() as conn:
        rows = conn.execute(
            "SELECT rowid, player1, player2, side, odds FROM value_picks WHERE result IS NULL",
        ).fetchall()
    return {int(r["rowid"]): dict(r) for r in rows}


def _notify_newly_settled(open_before: Dict[int, Dict[str, Any]]) -> int:
    from .. import db
    from .. import realtime_alerts as realtime_alerts_mod

    if not open_before or not realtime_alerts_mod.get():
        return 0

    notified = 0
    with db.connect() as conn:
        for rowid in list(open_before):
            row = conn.execute(
                "SELECT result, pnl, winner FROM value_picks "
                "WHERE rowid=? AND result IS NOT NULL",
                (rowid,),
            ).fetchone()
            if not row:
                continue
            pick = open_before[rowid]
            threading.Thread(
                target=realtime_alerts_mod.on_settlement,
                args=(
                    pick["player1"],
                    pick["player2"],
                    row["winner"] or "",
                    pick["side"],
                    float(pick["odds"] or 0),
                    float(row["pnl"] or 0),
                ),
                daemon=True,
                name=f"settlement-alert-{rowid}",
            ).start()
            notified += 1
    return notified


def _void_stale_open_picks(hours: int = STALE_VOID_HOURS) -> int:
    from .. import db

    cutoff = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=hours)).isoformat()
    with db.connect() as conn:
        stale = conn.execute(
            "SELECT rowid, player1, player2, date FROM value_picks "
            "WHERE result IS NULL AND date < ?",
            (cutoff,),
        ).fetchall()
    for row in stale:
        db.settle_value_pick(row["player1"], row["player2"], None)
        log(
            f"Void stale pick: {row['player1']} vs {row['player2']} ({row['date']})",
            "WARN",
        )
    return len(stale)


def run_settlement_once(
    deps: SettlementDeps,
    *,
    days_back: int = DEFAULT_DAYS_BACK,
) -> Dict[str, Any]:
    """Run one settlement cycle (testable, no sleep)."""
    from .. import db, mistake_learner, settlement

    open_before = _snapshot_open_value_picks()
    summary = settlement.run_settlement(deps.get_mem(), deps.resolve, days_back=days_back)

    notified = 0
    if summary.get("added", 0):
        notified = _notify_newly_settled(open_before)

    deps.refit_calibration()
    metrics = settlement.calibration_metrics()
    if metrics["n"] > 0:
        db.save_calibration(metrics)

    calib_k = deps.get_calib_k()
    log(
        f"Settlement auto: +{summary.get('added', 0)} réglés, "
        f"n={metrics['n']} acc={metrics.get('accuracy')} k={round(calib_k, 3)}",
    )

    try:
        mistake_learner.update()
    except Exception as exc:  # noqa: BLE001
        log(f"mistake_learner.update échoué: {exc}", "WARN")

    voided = _void_stale_open_picks()

    return {
        "settlement": summary,
        "metrics": metrics,
        "calibration_k": calib_k,
        "alerts_notified": notified,
        "stale_voided": voided,
        "open_before": len(open_before),
    }


def run_loop(
    *,
    interval: Optional[int] = None,
    deps: SettlementDeps,
    days_back: int = DEFAULT_DAYS_BACK,
    stop_event: Optional[threading.Event] = None,
) -> None:
    """Daemon loop: settle value picks every ``interval`` seconds.

    Matches pre-extraction behaviour: sleep *before* each cycle (including first).
    """
    _interval = interval if interval is not None else _env_int(
        "SETTLEMENT_INTERVAL_S", DEFAULT_LOOP_INTERVAL_S,
    )
    _stop = stop_event or threading.Event()

    log(f"Settlement worker démarré (intervalle {_interval}s).")

    while not _stop.is_set():
        if _stop.wait(_interval):
            break
        try:
            run_settlement_once(deps, days_back=days_back)
        except Exception as exc:  # noqa: BLE001
            log(f"Settlement auto en échec ({exc}).", "WARN")


def start_daemon_thread(
    *,
    interval: Optional[int] = None,
    deps: SettlementDeps,
    days_back: int = DEFAULT_DAYS_BACK,
) -> threading.Thread:
    """Start the worker in a daemon thread (used by ``api.serve()``)."""
    thread = threading.Thread(
        target=run_loop,
        kwargs={"interval": interval, "deps": deps, "days_back": days_back},
        daemon=True,
        name="value-settlement-worker",
    )
    thread.start()
    return thread
