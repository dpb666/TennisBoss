"""Tests for bot.workers.settlement_worker (Phase 4 api.py decomposition)."""
from __future__ import annotations

import threading
from unittest.mock import MagicMock, patch

from bot.workers.settlement_worker import SettlementDeps, run_settlement_once


def _deps(
    *,
    mem: dict | None = None,
    calib_k: float = 1.0,
) -> SettlementDeps:
    return SettlementDeps(
        get_mem=lambda: mem or {"players": {}},
        resolve=lambda n: n,
        refit_calibration=MagicMock(return_value={}),
        get_calib_k=lambda: calib_k,
    )


class TestRunSettlementOnce:
    def test_runs_settlement_and_refit(self):
        deps = _deps(calib_k=1.05)
        fake_summary = {"added": 2, "total": 10}

        with patch("bot.workers.settlement_worker.log"), patch(
            "bot.workers.settlement_worker._snapshot_open_value_picks",
            return_value={1: {"player1": "A", "player2": "B", "side": "A", "odds": 2.0}},
        ), patch("bot.settlement.run_settlement", return_value=fake_summary) as run_set, patch(
            "bot.workers.settlement_worker._notify_newly_settled", return_value=0,
        ), patch("bot.settlement.calibration_metrics", return_value={"n": 5, "accuracy": 0.6}), patch(
            "bot.db.save_calibration",
        ) as save_cal, patch("bot.mistake_learner.update") as ml_update, patch(
            "bot.workers.settlement_worker._void_stale_open_picks", return_value=0,
        ):
            out = run_settlement_once(deps, days_back=2)

        run_set.assert_called_once()
        deps.refit_calibration.assert_called_once()
        save_cal.assert_called_once()
        ml_update.assert_called_once()
        assert out["settlement"]["added"] == 2
        assert out["calibration_k"] == 1.05

    def test_notifies_when_picks_settled(self):
        deps = _deps()

        with patch("bot.workers.settlement_worker.log"), patch(
            "bot.workers.settlement_worker._snapshot_open_value_picks", return_value={1: {}},
        ), patch("bot.settlement.run_settlement", return_value={"added": 1}), patch(
            "bot.workers.settlement_worker._notify_newly_settled", return_value=1,
        ) as notify, patch("bot.settlement.calibration_metrics", return_value={"n": 0}), patch(
            "bot.mistake_learner.update",
        ), patch("bot.workers.settlement_worker._void_stale_open_picks", return_value=0):
            out = run_settlement_once(deps)

        notify.assert_called_once()
        assert out["alerts_notified"] == 1

    def test_voids_stale_picks(self):
        deps = _deps()

        with patch("bot.workers.settlement_worker.log"), patch(
            "bot.workers.settlement_worker._snapshot_open_value_picks", return_value={},
        ), patch("bot.settlement.run_settlement", return_value={"added": 0}), patch(
            "bot.workers.settlement_worker._notify_newly_settled", return_value=0,
        ), patch("bot.settlement.calibration_metrics", return_value={"n": 0}), patch(
            "bot.mistake_learner.update",
        ), patch("bot.workers.settlement_worker._void_stale_open_picks", return_value=2):
            out = run_settlement_once(deps)

        assert out["stale_voided"] == 2

    def test_survives_mistake_learner_failure(self):
        deps = _deps()

        with patch("bot.workers.settlement_worker.log"), patch(
            "bot.workers.settlement_worker._snapshot_open_value_picks", return_value={},
        ), patch("bot.settlement.run_settlement", return_value={"added": 0}), patch(
            "bot.workers.settlement_worker._notify_newly_settled", return_value=0,
        ), patch("bot.settlement.calibration_metrics", return_value={"n": 0}), patch(
            "bot.mistake_learner.update", side_effect=RuntimeError("ml"),
        ), patch("bot.workers.settlement_worker._void_stale_open_picks", return_value=0):
            out = run_settlement_once(deps)

        assert out["settlement"]["added"] == 0


class TestVoidStaleOpenPicks:
    def test_voids_old_rows(self):
        from bot.workers import settlement_worker as worker

        stale_row = {"player1": "A", "player2": "B", "date": "2020-01-01"}

        with patch.object(worker, "log"), patch("bot.db.connect") as conn_ctx, patch(
            "bot.db.settle_value_pick",
        ) as settle:
            conn = MagicMock()
            conn_ctx.return_value.__enter__.return_value = conn
            conn.execute.return_value.fetchall.return_value = [stale_row]
            count = worker._void_stale_open_picks(hours=48)

        assert count == 1
        settle.assert_called_once_with("A", "B", None)


class TestRunLoop:
    def test_sleeps_before_first_cycle(self):
        from bot.workers import settlement_worker as worker

        stop = threading.Event()
        stop.set()
        deps = _deps()

        with patch.object(worker, "log"), patch.object(worker, "run_settlement_once") as once:
            worker.run_loop(interval=600, deps=deps, stop_event=stop)

        once.assert_not_called()

    def test_runs_cycle(self):
        from bot.workers import settlement_worker as worker

        stop = threading.Event()
        deps = _deps()

        def _run(*_a, **_k):
            stop.set()
            return {}

        with patch.object(worker, "log"), patch.object(
            worker, "run_settlement_once", side_effect=_run,
        ) as once, patch.object(stop, "wait", return_value=False):
            worker.run_loop(interval=600, deps=deps, stop_event=stop)

        once.assert_called_once()


class TestApiShim:
    def test_settlement_loop_delegates(self):
        from bot import api

        with patch("bot.workers.settlement_worker.run_loop") as run_loop, patch(
            "bot.workers.settlement_worker.SettlementDeps",
        ) as deps_cls:
            api._settlement_loop(120)
        deps_cls.assert_called_once()
        run_loop.assert_called_once()
        assert run_loop.call_args.kwargs["interval"] == 120
