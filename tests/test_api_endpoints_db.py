"""Tests HTTP pour les endpoints qui touchent la DB directement (SQL brut,
pas de fonction mockable proprement) : /api/value/open, /api/value/history,
/api/history, /api/inplay/picks (CRUD), /api/recommendations.

Utilise une DB SQLite temporaire (même pattern que
tests/test_settlement.py::TestCalibrationMetrics) plutôt que des mocks,
car ces endpoints exécutent des requêtes SQL en ligne dans le handler.
"""
from __future__ import annotations

import os
import tempfile
import unittest
from unittest.mock import patch

from bot import api, config, db


class ApiDbTestCase(unittest.TestCase):
    def setUp(self):
        self._fd, self._path = tempfile.mkstemp(suffix=".db")
        self._save = config.DB_FILE
        config.DB_FILE = self._path
        db.init()
        api._MEM = {
            "players": {}, "elo": {}, "elo_surface": {}, "weights": {},
            "bias": 0.0, "metrics": {}, "datasets_loaded": [],
        }
        api.app.testing = True
        self.client = api.app.test_client()

    def tearDown(self):
        config.DB_FILE = self._save
        os.close(self._fd)
        os.remove(self._path)


class TestValueOpenAndHistory(ApiDbTestCase):
    def test_value_open_lists_unsettled_picks(self):
        db.log_value_pick("2026-07-01", "A", "B", "A", 2.5, 12.0)
        resp = self.client.get("/api/value/open")
        data = resp.get_json()
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(data["count"], 1)
        self.assertEqual(data["picks"][0]["side"], "A")

    def test_value_history_includes_settled_pick_with_pnl(self):
        db.log_value_pick("2026-07-01", "A", "B", "A", 2.5, 12.0)
        db.settle_value_pick("A", "B", "A")
        resp = self.client.get("/api/value/history")
        data = resp.get_json()
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(data["picks"]), 1)
        self.assertEqual(data["picks"][0]["result"], 1)
        self.assertIn("pnl", data["stats"])


class TestHistory(ApiDbTestCase):
    def test_history_by_date_returns_settled_matches(self):
        db.insert_settled({
            "event_key": "e1", "date": "2026-07-01", "tour": "atp",
            "tournament": "Test Open", "player1": "A", "player2": "B",
            "winner": "A", "final_score": "6-4 6-3",
            "pred_favorite": "A", "correct": 1,
        })
        resp = self.client.get("/api/history?date=2026-07-01")
        data = resp.get_json()
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(data["count"], 1)
        self.assertEqual(data["matches"][0]["winner"], "A")
        self.assertEqual(data["accuracy_day"], 1.0)

    def test_history_dates_lists_available_days(self):
        db.insert_settled({
            "event_key": "e1", "date": "2026-07-01", "tour": "atp",
            "player1": "A", "player2": "B", "winner": "A",
        })
        resp = self.client.get("/api/history?dates=1")
        data = resp.get_json()
        self.assertEqual(resp.status_code, 200)
        self.assertIn("2026-07-01", data["dates"])


class TestInplayPicksCrud(ApiDbTestCase):
    def test_full_lifecycle_log_settle_delete(self):
        # GET vide au départ.
        resp = self.client.get("/api/inplay/picks")
        self.assertEqual(resp.get_json()["picks"], [])

        # POST : log d'un nouveau pick.
        resp = self.client.post("/api/inplay/picks", json={
            "player1": "A", "player2": "B", "market_type": "set_winner",
            "pick": "A", "prob": 0.6,
        })
        self.assertEqual(resp.status_code, 201)
        pick_id = resp.get_json()["id"]

        resp = self.client.get("/api/inplay/picks")
        self.assertEqual(len(resp.get_json()["picks"]), 1)

        # PUT : règlement du pick.
        resp = self.client.put(f"/api/inplay/picks/{pick_id}", json={"result": "W"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_json()["result"], "W")

        # DELETE.
        resp = self.client.delete(f"/api/inplay/picks/{pick_id}")
        self.assertEqual(resp.status_code, 200)
        resp = self.client.get("/api/inplay/picks")
        self.assertEqual(resp.get_json()["picks"], [])

    def test_post_requires_mandatory_fields(self):
        resp = self.client.post("/api/inplay/picks", json={"player1": "A"})
        self.assertEqual(resp.status_code, 400)

    def test_post_rejects_longshot_winner_market(self):
        resp = self.client.post("/api/inplay/picks", json={
            "player1": "A", "player2": "B", "market_type": "match_winner",
            "pick": "A", "prob": 0.3, "odds": 8.0,
        })
        self.assertEqual(resp.status_code, 422)

    def test_put_requires_valid_result(self):
        resp = self.client.put("/api/inplay/picks/1", json={"result": "X"})
        self.assertEqual(resp.status_code, 400)

    def test_put_returns_404_for_unknown_pick(self):
        resp = self.client.put("/api/inplay/picks/999999", json={"result": "W"})
        self.assertEqual(resp.status_code, 404)

    def test_delete_returns_404_for_unknown_pick(self):
        resp = self.client.delete("/api/inplay/picks/999999")
        self.assertEqual(resp.status_code, 404)


class TestDeviceTokens(ApiDbTestCase):
    def test_register_is_idempotent_and_listable(self):
        db.register_device_token("tok1")
        db.register_device_token("tok1")  # ré-enregistrement : ne doit pas dupliquer
        db.register_device_token("tok2", platform="android")
        tokens = {r["token"] for r in db.list_device_tokens()}
        self.assertEqual(tokens, {"tok1", "tok2"})

    def test_delete_removes_token(self):
        db.register_device_token("tok1")
        db.delete_device_token("tok1")
        self.assertEqual(list(db.list_device_tokens()), [])


class TestRecommendations(ApiDbTestCase):
    def test_scores_matches_using_real_history(self):
        for _ in range(3):
            db.log_prediction("Sinner", "Nobody", 0.6, "Sinner")

        with api.app.app_context():
            fake_upcoming = api.jsonify({"count": 2, "matches": [
                {"prediction": {"player1": "Random1", "player2": "Random2"}},
                {"prediction": {"player1": "Sinner", "player2": "Alcaraz"}},
            ]})
        with patch.object(api, "api_upcoming", return_value=fake_upcoming):
            resp = self.client.get("/api/recommendations")

        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertIn("Sinner", data["favorite_players"])
        self.assertEqual(len(data["matches"]), 1)
        self.assertEqual(data["matches"][0]["prediction"]["player1"], "Sinner")

    def test_empty_matches_when_no_upcoming_fixtures(self):
        with api.app.app_context():
            fake_upcoming = api.jsonify({"count": 0, "matches": []})
        with patch.object(api, "api_upcoming", return_value=fake_upcoming):
            resp = self.client.get("/api/recommendations")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_json()["matches"], [])


if __name__ == "__main__":
    unittest.main()
