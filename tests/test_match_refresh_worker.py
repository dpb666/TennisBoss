"""Tests for bot.workers.match_refresh_worker (Phase 1 api.py decomposition)."""
from __future__ import annotations

import threading
from unittest.mock import patch

from bot.workers import match_refresh_worker as worker


def _watch_row(
    p1: str = "Player A",
    p2: str = "Player B",
    *,
    event_key: str = "evt-1",
    prev_h: float | None = 2.0,
    prev_a: float | None = 1.8,
) -> dict:
    return {
        "player1": p1,
        "player2": p2,
        "event_key": event_key,
        "last_odds_home": prev_h,
        "last_odds_away": prev_a,
    }


class TestRefreshWatchlistOnce:
    def test_skips_empty_watchlist(self):
        with patch.object(worker, "log"), patch("bot.db.list_followed_matches", return_value=[]):
            out = worker.refresh_watchlist_once()
        assert out["skipped"] is True
        assert out["reason"] == "empty_watchlist"
        assert out["refreshed"] == 0

    def test_skips_when_odds_api_disabled(self):
        rows = [_watch_row()]
        with patch.object(worker, "log"), patch("bot.db.list_followed_matches", return_value=rows), patch(
            "bot.odds_api.is_enabled", return_value=False,
        ):
            out = worker.refresh_watchlist_once()
        assert out["skipped"] is True
        assert out["reason"] == "odds_api_unavailable"

    def test_skips_when_no_api_key(self):
        rows = [_watch_row()]
        with patch.object(worker, "log"), patch("bot.db.list_followed_matches", return_value=rows), patch(
            "bot.odds_api.is_enabled", return_value=True,
        ), patch("bot.odds_api._current_key", return_value=None):
            out = worker.refresh_watchlist_once()
        assert out["skipped"] is True
        assert out["reason"] == "odds_api_unavailable"

    def test_refreshes_odds_and_persists(self):
        rows = [_watch_row()]
        event = {"id": "evt-1", "status": "pending"}
        mw = {"home_odds": 2.04, "away_odds": 1.79}  # <3% move vs prev 2.0 / 1.8

        with patch.object(worker, "log"), patch("bot.db.list_followed_matches", return_value=rows), patch(
            "bot.odds_api.is_enabled", return_value=True,
        ), patch("bot.odds_api._current_key", return_value="key"), patch(
            "bot.odds_api.fetch_tennis_events", return_value=[event],
        ), patch("bot.odds_api.build_event_index", return_value={"player a|player b": event}), patch(
            "bot.odds_api.find_event", return_value=event,
        ), patch("bot.odds_api.fetch_match_winner", return_value=mw) as fetch_mw, patch(
            "bot.db.update_followed_match_odds",
        ) as upd, patch("bot.db.record_market_snapshot") as snap, patch(
            "bot.realtime_alerts.on_odds_move",
        ) as alert:
            out = worker.refresh_watchlist_once()

        assert out["refreshed"] == 1
        fetch_mw.assert_called_once_with("evt-1", ttl=60)
        upd.assert_called_once_with("evt-1", 2.04, 1.79)
        snap.assert_called_once_with("evt-1", "Player A", "Player B", 2.04, 1.79)
        alert.assert_not_called()

    def test_live_event_uses_shorter_ttl(self):
        rows = [_watch_row()]
        event = {"id": "evt-1", "status": "live"}
        mw = {"home_odds": 1.9, "away_odds": 1.95}

        with patch.object(worker, "log"), patch("bot.db.list_followed_matches", return_value=rows), patch(
            "bot.odds_api.is_enabled", return_value=True,
        ), patch("bot.odds_api._current_key", return_value="key"), patch(
            "bot.odds_api.fetch_tennis_events", return_value=[event],
        ), patch("bot.odds_api.build_event_index", return_value={}), patch(
            "bot.odds_api.find_event", return_value=event,
        ), patch("bot.odds_api.fetch_match_winner", return_value=mw) as fetch_mw, patch(
            "bot.db.update_followed_match_odds",
        ), patch("bot.db.record_market_snapshot"), patch("bot.realtime_alerts.on_odds_move"):
            worker.refresh_watchlist_once()

        fetch_mw.assert_called_once_with("evt-1", ttl=30)

    def test_fires_steam_alert_on_large_move(self):
        rows = [_watch_row(prev_h=2.0, prev_a=1.8)]
        event = {"id": "evt-1", "status": "pending"}
        mw = {"home_odds": 2.12, "away_odds": 1.70}  # home +6%, away -5.5%

        with patch.object(worker, "log"), patch("bot.db.list_followed_matches", return_value=rows), patch(
            "bot.odds_api.is_enabled", return_value=True,
        ), patch("bot.odds_api._current_key", return_value="key"), patch(
            "bot.odds_api.fetch_tennis_events", return_value=[event],
        ), patch("bot.odds_api.build_event_index", return_value={}), patch(
            "bot.odds_api.find_event", return_value=event,
        ), patch("bot.odds_api.fetch_match_winner", return_value=mw), patch(
            "bot.db.update_followed_match_odds",
        ), patch("bot.db.record_market_snapshot"), patch(
            "bot.realtime_alerts.on_odds_move",
        ) as alert:
            worker.refresh_watchlist_once()

        assert alert.call_count == 2


class TestRunLoop:
    def test_stops_on_event_before_first_cycle(self):
        stop = threading.Event()
        stop.set()
        with patch.object(worker, "log"), patch.object(worker, "refresh_watchlist_once") as once:
            worker.run_loop(startup_delay=0, interval=60, stop_event=stop)
        once.assert_not_called()

    def test_runs_one_cycle_then_stops(self):
        stop = threading.Event()

        def _once_and_stop(*_a, **_k):
            stop.set()
            return {"refreshed": 0, "skipped": True}

        with patch.object(worker, "log"), patch.object(worker, "refresh_watchlist_once", side_effect=_once_and_stop):
            worker.run_loop(startup_delay=0, interval=999, stop_event=stop)

    def test_logs_and_continues_after_cycle_error(self):
        stop = threading.Event()
        calls = {"n": 0}

        def _fail_then_stop(*_a, **_k):
            calls["n"] += 1
            if calls["n"] >= 1:
                stop.set()
            raise OSError("network")

        with patch.object(worker, "log"), patch.object(worker, "refresh_watchlist_once", side_effect=_fail_then_stop):
            worker.run_loop(startup_delay=0, interval=0, stop_event=stop)

        assert calls["n"] == 1


class TestApiShim:
    def test_followed_matches_refresh_loop_delegates(self):
        from bot import api

        with patch("bot.workers.match_refresh_worker.run_loop") as run_loop:
            api._followed_matches_refresh_loop()
        run_loop.assert_called_once()
