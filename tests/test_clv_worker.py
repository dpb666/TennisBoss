"""Tests for bot.workers.clv_worker (Phase 3 api.py decomposition)."""
from __future__ import annotations

import threading
from unittest.mock import patch

from bot.workers import clv_worker as worker


def _open_pick(
    *,
    p1: str = "Player A",
    p2: str = "Player B",
    side: str = "Player A",
    event_key: str = "evt-1",
    pick_odds: float = 2.0,
) -> dict:
    return {
        "player1": p1,
        "player2": p2,
        "pick_side": side,
        "event_key": event_key,
        "pick_odds": pick_odds,
    }


class TestRefreshClvOnce:
    def test_skips_when_no_open_picks(self):
        with patch("bot.db.list_clv_open", return_value=[]):
            out = worker.refresh_clv_once()
        assert out["skipped"] is True
        assert out["reason"] == "no_open_clv_picks"

    def test_skips_when_odds_api_unavailable(self):
        picks = [_open_pick()]
        with patch("bot.db.list_clv_open", return_value=picks), patch(
            "bot.odds_api.is_enabled", return_value=False,
        ):
            out = worker.refresh_clv_once()
        assert out["skipped"] is True
        assert out["reason"] == "odds_api_unavailable"

    def test_updates_prematch_closing(self):
        picks = [_open_pick()]
        prematch_ev = {"id": "evt-1", "status": "pending", "date": "2026-07-17"}
        mw = {"home_odds": 2.05, "away_odds": 1.80}
        sharp = {"home_odds": 2.00, "away_odds": 1.85}

        with patch.object(worker, "log"), patch("bot.db.list_clv_open", return_value=picks), patch(
            "bot.odds_api.is_enabled", return_value=True,
        ), patch("bot.odds_api._current_key", return_value="key"), patch(
            "bot.odds_api.fetch_tennis_events", return_value=[prematch_ev],
        ), patch("bot.odds_api.build_event_index", side_effect=[{"player a|player b": prematch_ev}, {}]), patch(
            "bot.odds_api.find_event", side_effect=[None, prematch_ev],
        ), patch("bot.odds_api.fetch_match_winner", side_effect=[mw, sharp]), patch(
            "bot.odds_api._sharp_book", return_value="betfair",
        ), patch("bot.clv.refresh_closing") as refresh, patch(
            "bot.realtime_alerts.on_odds_move",
        ) as alert:
            out = worker.refresh_clv_once()

        assert out["closing_updated"] == 1
        refresh.assert_called_once()
        alert.assert_called_once()

    def test_live_settle_when_match_finished(self):
        picks = [_open_pick()]
        live_ev = {
            "id": "live-1",
            "status": "live",
            "home": "Player A",
            "away": "Player B",
            "scores": {"home": 2, "away": 0},
        }

        with patch.object(worker, "log"), patch("bot.db.list_clv_open", return_value=picks), patch(
            "bot.odds_api.is_enabled", return_value=True,
        ), patch("bot.odds_api._current_key", return_value="key"), patch(
            "bot.odds_api.fetch_tennis_events", return_value=[live_ev],
        ), patch("bot.odds_api.build_event_index", side_effect=[{}, {"player a|player b": live_ev}]), patch(
            "bot.odds_api.find_event", return_value=live_ev,
        ), patch("bot.clv.settle") as settle, patch("bot.clv.refresh_closing") as refresh:
            out = worker.refresh_clv_once()

        settle.assert_called_once_with("Player A", "Player B", "Player A")
        refresh.assert_not_called()
        assert out["settled_live"] == 1
        assert out["closing_updated"] == 0

    def test_live_in_progress_skips_closing(self):
        picks = [_open_pick()]
        live_ev = {
            "status": "live",
            "scores": {"home": 1, "away": 0},
            "home": "Player A",
            "away": "Player B",
        }

        with patch.object(worker, "log"), patch("bot.db.list_clv_open", return_value=picks), patch(
            "bot.odds_api.is_enabled", return_value=True,
        ), patch("bot.odds_api._current_key", return_value="key"), patch(
            "bot.odds_api.fetch_tennis_events", return_value=[live_ev],
        ), patch("bot.odds_api.build_event_index", side_effect=[{}, {}]), patch(
            "bot.odds_api.find_event", return_value=live_ev,
        ), patch("bot.clv.settle") as settle, patch("bot.clv.refresh_closing") as refresh:
            out = worker.refresh_clv_once()

        settle.assert_not_called()
        refresh.assert_not_called()
        assert out["settled_live"] == 0


class TestSetsTarget:
    def test_bo3(self):
        assert worker._sets_target(1, 0) == 2

    def test_bo5(self):
        assert worker._sets_target(3, 1) == 3


class TestRunLoop:
    def test_respects_startup_delay(self):
        stop = threading.Event()
        stop.set()
        with patch.object(worker, "log"), patch.object(worker, "refresh_clv_once") as once:
            worker.run_loop(startup_delay=0, interval=600, stop_event=stop)
        once.assert_not_called()

    def test_runs_cycle(self):
        stop = threading.Event()

        def _refresh(*_a, **_k):
            stop.set()
            return {"closing_updated": 0}

        with patch.object(worker, "log"), patch.object(
            worker, "refresh_clv_once", side_effect=_refresh,
        ) as once, patch.object(stop, "wait", return_value=False):
            worker.run_loop(startup_delay=0, interval=600, stop_event=stop)

        once.assert_called_once()


class TestApiShim:
    def test_clv_closing_loop_delegates(self):
        from bot import api

        with patch("bot.workers.clv_worker.run_loop") as run_loop:
            api._clv_closing_loop()
        run_loop.assert_called_once()
