"""Tests bet_history : table, stats, API et hook settlement CLV."""
from __future__ import annotations

import os
import tempfile
import unittest

from bot import api, clv, config, db


class BetHistoryTestCase(unittest.TestCase):
    def setUp(self):
        self._fd, self._path = tempfile.mkstemp(suffix=".db")
        self._save = config.DB_FILE
        config.DB_FILE = self._path
        db.init()

    def tearDown(self):
        config.DB_FILE = self._save
        os.close(self._fd)
        os.remove(self._path)


class TestBetHistoryDb(BetHistoryTestCase):
    def test_log_and_list_bet_history(self):
        rid = db.log_bet_history({
            "event_key": "ev1",
            "player1": "A", "player2": "B",
            "date": "2026-07-01",
            "prediction": 0.62, "pick_side": "A",
            "odds": 1.85, "confidence": 0.72,
            "result": 1, "profit_loss": 0.85,
            "clv_pct": 3.5, "surface": "hard",
            "model_version": "test-v1",
        })
        self.assertGreater(rid, 0)
        rows = db.list_bet_history(limit=10)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["event_key"], "ev1")
        self.assertEqual(rows[0]["pick_side"], "A")

    def test_log_bet_history_dedup_event_key(self):
        row = {
            "event_key": "ev-dup",
            "player1": "A", "player2": "B", "date": "2026-07-01",
            "pick_side": "A", "odds": 2.0, "result": 1, "profit_loss": 1.0,
        }
        self.assertGreater(db.log_bet_history(row), 0)
        self.assertEqual(db.log_bet_history(row), 0)
        self.assertEqual(len(db.list_bet_history()), 1)

    def test_bet_history_stats_roi_and_surface(self):
        db.log_bet_history({
            "event_key": "w1", "player1": "A", "player2": "B",
            "date": "2026-07-10", "pick_side": "A", "odds": 2.0,
            "confidence": 0.80, "result": 1, "profit_loss": 1.0,
            "surface": "hard", "model_version": "v1", "bookmaker": "bet365",
            "clv_pct": 4.0, "prediction": 0.62,
        })
        db.log_bet_history({
            "event_key": "w2", "player1": "C", "player2": "D",
            "date": "2026-07-11", "pick_side": "C", "odds": 1.90,
            "confidence": 0.65, "result": 0, "profit_loss": -1.0,
            "surface": "clay", "model_version": "v1", "bookmaker": "pinnacle",
            "clv_pct": -1.0, "prediction": 0.58,
        })
        stats = db.bet_history_stats(days=30)
        self.assertEqual(stats["n"], 2)
        self.assertEqual(stats["wins"], 1)
        self.assertEqual(stats["win_rate"], 0.5)
        self.assertEqual(stats["roi"], 0.0)
        self.assertEqual(stats["yield_pct"], 0.0)
        self.assertAlmostEqual(stats["avg_clv_pct"], 1.5)
        self.assertIn("hard", stats["by_surface"])
        self.assertIn("clay", stats["by_surface"])
        self.assertIn("bet365", stats["by_bookmaker"])
        self.assertEqual(len(stats["calibration_bins"]), 5)

    def test_bet_history_calibration_bins(self):
        db.log_bet_history({
            "event_key": "c1", "player1": "A", "player2": "B",
            "date": "2026-07-12", "pick_side": "A", "odds": 1.80,
            "prediction": 0.62, "result": 1, "profit_loss": 0.80,
        })
        db.log_bet_history({
            "event_key": "c2", "player1": "C", "player2": "D",
            "date": "2026-07-12", "pick_side": "C", "odds": 2.00,
            "prediction": 0.72, "result": 0, "profit_loss": -1.0,
        })
        cal = db.bet_history_calibration(days=30)
        self.assertEqual(cal["n_settled"], 2)
        self.assertEqual(len(cal["bins"]), 6)
        self.assertIsNotNone(cal["brier_score"])

    def test_backfill_bet_history_from_clv(self):
        clv.seed_pick("bf1", "2026-07-10", "A", "B", "A", 2.0, 0.60, 0.70)
        clv.refresh_closing("bf1", "A", "A", 1.90, 2.1)
        clv.settle("A", "B", "A")
        db.log_value_pick("2026-07-10", "A", "B", "A", 2.0, 10.0, surface="clay")
        result = db.backfill_bet_history_from_clv(limit=10)
        rows = db.list_bet_history()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["surface"], "clay")
        self.assertGreaterEqual(result["added"] + result["patched"], 1)

    def test_sync_from_clv_settle_hook(self):
        clv.seed_pick("hook1", "2026-07-12", "A", "B", "A", 2.0, 0.58, 0.70)
        clv.refresh_closing("hook1", "A", "A", 1.90, 2.1)
        db.log_value_pick("2026-07-12", "A", "B", "A", 2.0, 10.0, surface="grass")
        self.assertTrue(clv.settle("A", "B", "A"))
        rows = db.list_bet_history()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["event_key"], "hook1")
        self.assertEqual(rows[0]["surface"], "grass")
        self.assertAlmostEqual(rows[0]["profit_loss"], 1.0)
        self.assertIsNotNone(rows[0]["clv_pct"])

    def test_sync_from_value_pick_only(self):
        db.log_value_pick("2026-07-13", "X", "Y", "X", 2.5, 12.0, surface="hard")
        db.settle_value_pick("X", "Y", "X")
        db.sync_bet_history_on_settle("X", "Y", "X")
        rows = db.list_bet_history()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["pick_side"], "X")
        self.assertEqual(rows[0]["result"], 1)

    def test_resolve_surface_from_archive_when_value_pick_empty(self):
        db.archive_matches([{
            "id": 1, "date": "20260710", "tour": "atp",
            "winner_name": "A", "loser_name": "B",
            "winner": {"serve": 0.5, "return1": 0.5, "return2": 0.5},
            "loser": {"serve": 0.5, "return1": 0.5, "return2": 0.5},
            "surface": "clay", "margin": 2,
        }])
        surf = db.resolve_bet_surface("A", "B", "2026-07-10")
        self.assertEqual(surf, "clay")

    def test_backfill_surface_from_matches_archive(self):
        db.archive_matches([{
            "id": 2, "date": "20260711", "tour": "atp",
            "winner_name": "C", "loser_name": "D",
            "winner": {"serve": 0.5, "return1": 0.5, "return2": 0.5},
            "loser": {"serve": 0.5, "return1": 0.5, "return2": 0.5},
            "surface": "grass", "margin": 2,
        }])
        db.log_bet_history({
            "event_key": "arch1", "player1": "C", "player2": "D",
            "date": "2026-07-11", "pick_side": "C", "odds": 2.0,
            "prediction": 0.6, "result": 1, "profit_loss": 1.0,
            "surface": "",
        })
        result = db.backfill_bet_history_surface_from_matches()
        self.assertEqual(result["patched"], 1)
        rows = db.list_bet_history()
        self.assertEqual(rows[0]["surface"], "grass")


class TestBetHistoryApi(BetHistoryTestCase):
    def setUp(self):
        super().setUp()
        import os
        self._token_save = os.environ.get("TENNISBOSS_API_TOKEN")
        os.environ["TENNISBOSS_API_TOKEN"] = ""
        api._MEM = {
            "players": {}, "elo": {}, "elo_surface": {}, "weights": {},
            "bias": 0.0, "metrics": {}, "datasets_loaded": [],
        }
        api.app.testing = True
        self.client = api.app.test_client()

    def tearDown(self):
        import os
        if self._token_save is None:
            os.environ.pop("TENNISBOSS_API_TOKEN", None)
        else:
            os.environ["TENNISBOSS_API_TOKEN"] = self._token_save
        super().tearDown()

    def test_api_bet_history_stats(self):
        db.log_bet_history({
            "event_key": "api1", "player1": "A", "player2": "B",
            "date": "2026-07-14", "pick_side": "A", "odds": 1.80,
            "result": 1, "profit_loss": 0.80, "surface": "hard",
        })
        resp = self.client.get("/api/bet-history/stats?days=30")
        data = resp.get_json()
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(data["n"], 1)
        self.assertEqual(data["win_rate"], 1.0)

    def test_api_bet_history_recent(self):
        db.log_bet_history({
            "event_key": "api2", "player1": "C", "player2": "D",
            "date": "2026-07-14", "pick_side": "C", "odds": 2.10,
            "result": 0, "profit_loss": -1.0,
        })
        resp = self.client.get("/api/bet-history/recent?limit=10")
        data = resp.get_json()
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(data["count"], 1)
        self.assertEqual(data["bets"][0]["player1"], "C")

    def test_api_bet_history_calibration(self):
        db.log_bet_history({
            "event_key": "cal1", "player1": "A", "player2": "B",
            "date": "2026-07-14", "pick_side": "A", "odds": 1.85,
            "prediction": 0.65, "result": 1, "profit_loss": 0.85,
        })
        resp = self.client.get("/api/bet-history/calibration?days=90")
        data = resp.get_json()
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(data["n_settled"], 1)
        self.assertEqual(len(data["bins"]), 6)
        self.assertIn("brier_score", data)


if __name__ == "__main__":
    unittest.main()
