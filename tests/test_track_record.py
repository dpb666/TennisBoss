"""Tests Track Record — read layer + API endpoints."""
from __future__ import annotations

import os
import tempfile
import unittest

from bot import api, clv, config, db, track_record


class TrackRecordTestCase(unittest.TestCase):
    def setUp(self):
        self._fd, self._path = tempfile.mkstemp(suffix=".db")
        self._save_db = config.DB_FILE
        self._save_stake = config.TRACK_RECORD_STAKE
        config.DB_FILE = self._path
        config.TRACK_RECORD_STAKE = 1.0
        db.init()

    def tearDown(self):
        config.DB_FILE = self._save_db
        config.TRACK_RECORD_STAKE = self._save_stake
        os.close(self._fd)
        os.remove(self._path)


class TestTrackRecordModule(TrackRecordTestCase):
    def _seed_settled_pick(
        self,
        ek: str,
        date: str,
        p1: str,
        p2: str,
        side: str,
        odds: float,
        winner: str,
        *,
        surface: str = "hard",
        tournament: str = "Test Open",
        closing: float = 1.90,
        ev_pct: float = 10.0,
        confidence: float = 0.72,
    ):
        repro = {
            "tournament": tournament,
            "tournament_level": "tour",
            "surface": surface,
            "ev_pct": ev_pct,
            "predictor_version": "1.0-test",
            "calibration_version": "1.0-test",
        }
        clv.seed_pick(ek, date, p1, p2, side, odds, 0.60, confidence, repro=repro)
        clv.refresh_closing(ek, side, p1, closing if side == p1 else 2.5,
                            2.5 if side == p1 else closing)
        clv.settle(p1, p2, winner)
        db.sync_bet_history_on_settle(p1, p2, winner, event_key=ek)

    def test_empty_summary(self):
        s = track_record.summary(days=30)
        self.assertEqual(s["settled_picks"], 0)
        self.assertIsNone(s["win_rate"])
        self.assertIsNone(s["roi"])
        self.assertEqual(s["longest_win_streak"], 0)

    def test_list_picks_enriched_from_clv(self):
        self._seed_settled_pick("tr1", "2026-07-10", "A", "B", "A", 2.0, "A",
                                tournament="Wimbledon", surface="grass")
        data = track_record.list_picks(days=30, limit=10)
        self.assertEqual(data["total"], 1)
        pick = data["picks"][0]
        self.assertEqual(pick["tournament"], "Wimbledon")
        self.assertEqual(pick["surface"], "grass")
        self.assertEqual(pick["result"], "win")
        self.assertEqual(pick["market"], "match_winner")
        self.assertTrue(pick["closing_odds_available"])
        self.assertEqual(pick["predictor_version"], "1.0-test")

    def test_summary_stats_and_streaks(self):
        self._seed_settled_pick("w1", "2026-07-10", "A", "B", "A", 2.0, "A")
        self._seed_settled_pick("w2", "2026-07-11", "C", "D", "C", 1.80, "C")
        self._seed_settled_pick("l1", "2026-07-12", "E", "F", "E", 2.10, "F")
        s = track_record.summary(days=30)
        self.assertEqual(s["settled_picks"], 3)
        self.assertEqual(s["wins"], 2)
        self.assertAlmostEqual(s["win_rate"], 2 / 3, places=2)
        self.assertGreater(s["net_units"], 0)
        self.assertEqual(s["longest_win_streak"], 2)
        self.assertEqual(s["longest_loss_streak"], 1)
        self.assertIsNotNone(s["avg_clv_pct"])

    def test_void_pick(self):
        db.log_bet_history({
            "event_key": "void1",
            "player1": "X", "player2": "Y",
            "date": "2026-07-13", "pick_side": "X",
            "odds": 2.0, "result": -1, "profit_loss": 0.0,
            "surface": "hard",
        })
        s = track_record.summary(days=30)
        self.assertEqual(s["void_picks"], 1)
        self.assertEqual(s["settled_picks"], 0)
        data = track_record.list_picks(days=30, result="void")
        self.assertEqual(data["total"], 1)
        self.assertEqual(data["picks"][0]["result"], "void")
        self.assertEqual(data["picks"][0]["profit_loss"], 0.0)

    def test_missing_closing_odds(self):
        db.log_bet_history({
            "event_key": "noclose",
            "player1": "M", "player2": "N",
            "date": "2026-07-14", "pick_side": "M",
            "odds": 1.95, "result": 1, "profit_loss": 0.95,
            "clv_pct": None, "surface": "clay", "confidence": 0.65,
        })
        pick = track_record.list_picks(days=30)["picks"][0]
        self.assertFalse(pick["closing_odds_available"])
        self.assertIsNone(pick["closing_odds"])
        s = track_record.summary(days=30)
        self.assertEqual(s["closing_odds_coverage_pct"], 0.0)

    def test_configurable_stake(self):
        config.TRACK_RECORD_STAKE = 2.0
        db.log_bet_history({
            "event_key": "stake1",
            "player1": "P", "player2": "Q",
            "date": "2026-07-15", "pick_side": "P",
            "odds": 2.0, "result": 1, "profit_loss": 1.0,
        })
        pick = track_record.list_picks(days=30)["picks"][0]
        self.assertEqual(pick["stake"], 2.0)
        self.assertEqual(pick["profit_loss"], 2.0)

    def test_surface_filter(self):
        db.log_bet_history({
            "event_key": "sf1", "player1": "A", "player2": "B",
            "date": "2026-07-16", "pick_side": "A", "odds": 2.0,
            "result": 1, "profit_loss": 1.0, "surface": "clay",
        })
        db.log_bet_history({
            "event_key": "sf2", "player1": "C", "player2": "D",
            "date": "2026-07-16", "pick_side": "C", "odds": 2.0,
            "result": 0, "profit_loss": -1.0, "surface": "hard",
        })
        clay = track_record.list_picks(days=30, surface="clay")
        self.assertEqual(clay["total"], 1)
        self.assertEqual(clay["picks"][0]["surface"], "clay")

    def test_monthly_and_surface_breakdown(self):
        db.log_bet_history({
            "event_key": "mb1", "player1": "A", "player2": "B",
            "date": "2026-07-10", "pick_side": "A", "odds": 2.0,
            "result": 1, "profit_loss": 1.0, "surface": "hard",
        })
        db.log_bet_history({
            "event_key": "mb2", "player1": "C", "player2": "D",
            "date": "2026-06-15", "pick_side": "C", "odds": 2.0,
            "result": 0, "profit_loss": -1.0, "surface": "clay",
        })
        monthly = track_record.monthly_breakdown(days=365)
        self.assertGreaterEqual(len(monthly["months"]), 2)
        surfaces = track_record.surface_breakdown(days=365)
        labels = {s["label"] for s in surfaces["surfaces"]}
        self.assertIn("hard", labels)
        self.assertIn("clay", labels)

    def test_pagination(self):
        for i in range(5):
            db.log_bet_history({
                "event_key": f"p{i}",
                "player1": f"P{i}", "player2": f"Q{i}",
                "date": f"2026-07-{10+i:02d}", "pick_side": f"P{i}",
                "odds": 2.0, "result": 1, "profit_loss": 1.0,
            })
        page1 = track_record.list_picks(days=365, page=1, limit=2)
        page2 = track_record.list_picks(days=365, page=2, limit=2)
        self.assertEqual(page1["total"], 5)
        self.assertEqual(len(page1["picks"]), 2)
        self.assertEqual(len(page2["picks"]), 2)
        self.assertNotEqual(page1["picks"][0]["id"], page2["picks"][0]["id"])

    def test_confidence_buckets(self):
        db.log_bet_history({
            "event_key": "cb1", "player1": "A", "player2": "B",
            "date": "2026-07-10", "pick_side": "A", "odds": 2.0,
            "result": 1, "profit_loss": 1.0, "confidence": 0.75,
        })
        s = track_record.summary(days=30)
        buckets = s["by_confidence"]
        self.assertTrue(any(b["n"] > 0 for b in buckets))


class TestTrackRecordApi(TrackRecordTestCase):
    def setUp(self):
        super().setUp()
        self._token_save = os.environ.get("TENNISBOSS_API_TOKEN")
        os.environ["TENNISBOSS_API_TOKEN"] = ""
        api._MEM = {
            "players": {}, "elo": {}, "elo_surface": {}, "weights": {},
            "bias": 0.0, "metrics": {}, "datasets_loaded": [],
        }
        api.app.testing = True
        self.client = api.app.test_client()

    def tearDown(self):
        if self._token_save is None:
            os.environ.pop("TENNISBOSS_API_TOKEN", None)
        else:
            os.environ["TENNISBOSS_API_TOKEN"] = self._token_save
        super().tearDown()

    def test_api_track_record_list(self):
        db.log_bet_history({
            "event_key": "api-tr1", "player1": "A", "player2": "B",
            "date": "2026-07-14", "pick_side": "A", "odds": 1.85,
            "result": 1, "profit_loss": 0.85, "surface": "hard",
        })
        resp = self.client.get("/api/track-record?days=30&limit=10")
        data = resp.get_json()
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(data["total"], 1)
        self.assertIn("picks", data)
        self.assertEqual(data["picks"][0]["selection"], "A")

    def test_api_track_record_summary(self):
        db.log_bet_history({
            "event_key": "api-tr2", "player1": "C", "player2": "D",
            "date": "2026-07-14", "pick_side": "C", "odds": 2.0,
            "result": 1, "profit_loss": 1.0,
        })
        resp = self.client.get("/api/track-record/summary?days=30")
        data = resp.get_json()
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(data["wins"], 1)
        self.assertIn("longest_win_streak", data)

    def test_api_track_record_monthly(self):
        db.log_bet_history({
            "event_key": "api-tr3", "player1": "E", "player2": "F",
            "date": "2026-07-01", "pick_side": "E", "odds": 2.0,
            "result": 0, "profit_loss": -1.0,
        })
        resp = self.client.get("/api/track-record/monthly?days=365")
        data = resp.get_json()
        self.assertEqual(resp.status_code, 200)
        self.assertIn("months", data)

    def test_api_track_record_surfaces(self):
        db.log_bet_history({
            "event_key": "api-tr4", "player1": "G", "player2": "H",
            "date": "2026-07-01", "pick_side": "G", "odds": 2.0,
            "result": 1, "profit_loss": 1.0, "surface": "grass",
        })
        resp = self.client.get("/api/track-record/surfaces?days=365")
        data = resp.get_json()
        self.assertEqual(resp.status_code, 200)
        self.assertIn("surfaces", data)

    def test_api_invalid_result_filter(self):
        resp = self.client.get("/api/track-record?result=maybe")
        self.assertEqual(resp.status_code, 400)


if __name__ == "__main__":
    unittest.main()
