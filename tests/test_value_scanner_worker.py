"""Tests for bot.workers.value_scanner (Phase 5 api.py decomposition)."""
from __future__ import annotations

import threading
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from bot.workers import value_scanner as scanner


def _deps(**overrides) -> scanner.ScannerDeps:
    defaults = {
        "get_mem": lambda: {"players": {"A": {"tour": "atp"}, "B": {"tour": "atp"}}},
        "resolve": lambda n: n,
        "calibrate_match_prob": lambda p: p,
        "get_calib_k": lambda: 1.0,
        "get_market_blend_w": lambda: 0.0,
        "build_pick_repro": lambda *a, **k: {},
        "set_to_match_prob": lambda p: p,
        "high_conf_min_ev": 15.0,
    }
    defaults.update(overrides)
    return scanner.ScannerDeps(**defaults)


class TestTournRank:
    def test_grand_slam(self):
        assert scanner._tourn_rank({"league": {"slug": "atp-wimbledon"}}) == 0

    def test_itf(self):
        assert scanner._tourn_rank({"league": {"slug": "itf-m25"}}) == 3


class TestRunScannerCycle:
    def test_skips_when_odds_disabled(self):
        session = scanner._ScannerSession()
        with patch("bot.odds_api.is_enabled", return_value=False):
            out = scanner.run_scanner_cycle(_deps(), session)
        assert out["skipped"] is True
        assert out["reason"] == "odds_api_unavailable"

    def test_empty_events_updates_state(self):
        session = scanner._ScannerSession()
        with patch("bot.workers.value_scanner.log"), patch(
            "bot.odds_api.is_enabled", return_value=True,
        ), patch("bot.odds_api._current_key", return_value="k"), patch(
            "bot.odds_api.fetch_tennis_events", return_value=[],
        ), patch("bot.db.get_all_player_rankings", return_value={}):
            out = scanner.run_scanner_cycle(_deps(), session)

        assert out["events_total"] == 0
        status = scanner.get_status()
        assert status["total_events"] == 0
        assert status["checked"] == 0

    def test_rejects_outside_time_window(self):
        session = scanner._ScannerSession()
        far_future = (datetime.now(timezone.utc) + timedelta(hours=10)).isoformat()
        events = [{"id": "e1", "commence_time": far_future, "home": "A", "away": "B"}]

        with patch("bot.workers.value_scanner.log"), patch(
            "bot.odds_api.is_enabled", return_value=True,
        ), patch("bot.odds_api._current_key", return_value="k"), patch(
            "bot.odds_api.fetch_tennis_events", return_value=events,
        ), patch("bot.db.get_all_player_rankings", return_value={}):
            scanner.run_scanner_cycle(_deps(), session)

        assert scanner.get_status()["rejections"]["fenetre"] == 1


class TestGetStatus:
    def test_returns_copy(self):
        with scanner.SCANNER_STATE_LOCK:
            scanner.SCANNER_STATE["running"] = True
        status = scanner.get_status()
        status["running"] = False
        assert scanner.get_status()["running"] is True


class TestRunLoop:
    def test_marks_running(self):
        stop = threading.Event()
        stop.set()
        with patch("bot.workers.value_scanner.log"), patch.object(
            scanner, "run_scanner_cycle", return_value={"skipped": True},
        ):
            scanner.run_loop(startup_delay=0, interval=90, deps=_deps(), stop_event=stop)
        assert scanner.get_status()["running"] is True


class TestApiIntegration:
    def test_scanner_status_endpoint(self):
        from bot import api

        with patch("bot.workers.value_scanner.get_status", return_value={"running": True, "checked": 3}):
            resp = api.app.test_client().get("/api/scanner/status")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["ok"] is True
        assert data["running"] is True

    def test_value_scanner_loop_delegates(self):
        from bot import api

        with patch("bot.workers.value_scanner.run_loop") as run_loop, patch(
            "bot.workers.value_scanner.ScannerDeps",
        ) as deps_cls:
            api._value_scanner_loop(120)
        deps_cls.assert_called_once()
        run_loop.assert_called_once()
        assert run_loop.call_args.kwargs["interval"] == 120
