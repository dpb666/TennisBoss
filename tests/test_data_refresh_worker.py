"""Tests for bot.workers.data_refresh_worker (Phase 7 api.py decomposition)."""
from __future__ import annotations

import datetime as dt
import threading
from unittest.mock import patch

from bot.workers import data_refresh_worker as worker


class TestRefreshDataOnce:
    def test_skips_when_not_refresh_hour(self):
        now = dt.datetime(2026, 7, 20, 10, 0, 0)
        state = worker.DataRefreshCycleState()

        with patch("bot.tennisdata_feeder.ingest") as ingest:
            out = worker.refresh_data_once(now=now, state=state)

        ingest.assert_not_called()
        assert out["skipped"] is True
        assert out["reason"] == "not_refresh_hour"
        assert out["refreshed"] is False

    def test_skips_when_already_refreshed_today(self):
        now = dt.datetime(2026, 7, 20, 2, 30, 0)
        state = worker.DataRefreshCycleState(refreshed_on="2026-07-20")

        with patch("bot.tennisdata_feeder.ingest") as ingest:
            out = worker.refresh_data_once(now=now, state=state)

        ingest.assert_not_called()
        assert out["skipped"] is True
        assert out["reason"] == "already_refreshed_today"

    def test_ingests_at_refresh_hour(self):
        now = dt.datetime(2026, 7, 20, 2, 0, 0)
        state = worker.DataRefreshCycleState()

        with patch.object(worker, "log"), patch(
            "bot.tennisdata_feeder.ingest", return_value={"inserted": 0},
        ) as ingest:
            out = worker.refresh_data_once(now=now, state=state)

        ingest.assert_called_once_with(years=[2026, 2025])
        assert out["refreshed"] is True
        assert out["inserted"] == 0
        assert out["elo_rebuilt"] is False
        assert state.refreshed_on == "2026-07-20"

    def test_rebuilds_elo_when_inserted(self):
        now = dt.datetime(2026, 7, 20, 2, 0, 0)
        state = worker.DataRefreshCycleState()
        rows = [{"winner": "A", "loser": "B"}]
        mem = {"elo": {}}

        with patch.object(worker, "log"), patch(
            "bot.tennisdata_feeder.ingest", return_value={"inserted": 3},
        ), patch("bot.db.all_matches_chrono", return_value=rows), patch(
            "bot.elo.update", side_effect=lambda e, w, l: e.update({w: 1500}),
        ), patch("bot.memory.load", return_value=mem), patch(
            "bot.memory.save",
        ) as save:
            out = worker.refresh_data_once(now=now, state=state)

        assert out["elo_rebuilt"] is True
        save.assert_called_once()
        assert mem["elo"] == {"A": 1500}

    def test_survives_ingest_error_in_run_loop(self):
        stop = threading.Event()

        with patch.object(worker, "log"), patch.object(
            worker, "refresh_data_once", side_effect=RuntimeError("network"),
        ), patch.object(stop, "wait", side_effect=[False, True]):
            worker.run_loop(startup_delay=0, interval=1800, stop_event=stop)


class TestRunLoop:
    def test_waits_startup_before_first_cycle(self):
        stop = threading.Event()
        calls: list[int] = []

        def _stop_after_wait(timeout: float) -> bool:
            calls.append(int(timeout))
            stop.set()
            return True

        with patch.object(worker, "log"), patch.object(worker, "refresh_data_once") as once:
            stop.wait = _stop_after_wait  # type: ignore[method-assign]
            worker.run_loop(startup_delay=60, interval=1800, stop_event=stop)

        once.assert_not_called()
        assert calls == [60]

    def test_runs_cycle_after_startup_and_interval(self):
        stop = threading.Event()
        state = worker.DataRefreshCycleState()

        with patch.object(worker, "log"), patch.object(
            worker, "refresh_data_once", return_value={"refreshed": False},
        ) as once, patch.object(stop, "wait", side_effect=[False, True]):
            worker.run_loop(
                startup_delay=0, interval=1800, stop_event=stop, state=state,
            )

        assert once.call_count == 2


class TestApiShim:
    def test_data_refresh_loop_delegates(self):
        from bot import api

        with patch("bot.workers.data_refresh_worker.run_loop") as run_loop:
            api._data_refresh_loop()
        run_loop.assert_called_once_with()
