"""Tests for bot.workers.inplay_settlement_worker (Phase 2 api.py decomposition)."""
from __future__ import annotations

import threading
from unittest.mock import patch

from bot.workers import inplay_settlement_worker as worker


class TestSettleInplayOnce:
    def test_skips_when_no_pending(self):
        with patch("bot.db.list_inplay_picks_pending", return_value=[]):
            out = worker.settle_inplay_once()
        assert out["skipped"] is True
        assert out["reason"] == "no_pending_picks"
        assert out["settled"] == 0

    def test_settles_with_live_ids(self):
        pending = [{"id": 1, "event_id": "e1"}]
        settled = [{"pick": "Player A", "result": "W", "pnl": 1.5}]

        with patch.object(worker, "log"), patch(
            "bot.db.list_inplay_picks_pending", return_value=pending,
        ), patch("bot.odds_api.fetch_live_events", return_value=[{"event_id": "e2"}]), patch(
            "bot.db.auto_settle_picks", return_value=settled,
        ) as auto_settle:
            out = worker.settle_inplay_once()

        auto_settle.assert_called_once_with({"e2"})
        assert out["pending"] == 1
        assert out["settled"] == 1
        assert out["settled_rows"] == settled

    def test_empty_live_ids_when_fetch_fails(self):
        pending = [{"id": 1}]

        with patch.object(worker, "log"), patch(
            "bot.db.list_inplay_picks_pending", return_value=pending,
        ), patch("bot.odds_api.fetch_live_events", side_effect=OSError("timeout")), patch(
            "bot.db.auto_settle_picks", return_value=[],
        ) as auto_settle:
            worker.settle_inplay_once()

        auto_settle.assert_called_once_with(set())

    def test_no_log_when_nothing_settled(self):
        with patch.object(worker, "log") as log_fn, patch(
            "bot.db.list_inplay_picks_pending", return_value=[{"id": 1}],
        ), patch("bot.odds_api.fetch_live_events", return_value=[]), patch(
            "bot.db.auto_settle_picks", return_value=[],
        ):
            worker.settle_inplay_once()

        info_calls = [c for c in log_fn.call_args_list if len(c[0]) > 1 and c[0][1] == "INFO"]
        assert not info_calls


class TestRunLoop:
    def test_sleeps_before_first_cycle(self):
        stop = threading.Event()
        calls: list[int] = []

        def _stop_after_wait(timeout: float) -> bool:
            calls.append(int(timeout))
            stop.set()
            return True

        with patch.object(worker, "log"), patch.object(worker, "settle_inplay_once") as once:
            stop.wait = _stop_after_wait  # type: ignore[method-assign]
            worker.run_loop(interval=300, stop_event=stop)

        once.assert_not_called()
        assert calls == [300]

    def test_runs_cycle_after_interval(self):
        stop = threading.Event()

        with patch.object(worker, "log"), patch.object(
            worker, "settle_inplay_once", return_value={"settled": 0},
        ) as once, patch.object(stop, "wait", side_effect=[False, True]):
            worker.run_loop(interval=300, stop_event=stop)

        once.assert_called_once()

    def test_survives_settlement_error(self):
        stop = threading.Event()

        with patch.object(worker, "log"), patch.object(
            worker, "settle_inplay_once", side_effect=RuntimeError("db locked"),
        ), patch.object(stop, "wait", side_effect=[False, True]):
            worker.run_loop(interval=300, stop_event=stop)


class TestApiShim:
    def test_inplay_settle_loop_delegates(self):
        from bot import api

        with patch("bot.workers.inplay_settlement_worker.run_loop") as run_loop:
            api._inplay_settle_loop(120)
        run_loop.assert_called_once_with(interval=120)
