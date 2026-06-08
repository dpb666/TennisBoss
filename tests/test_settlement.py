"""Tests du settlement : parsing des résultats + métriques de calibration."""
import os
import tempfile
import unittest

from bot import config, db, live_api, settlement


class TestParseResult(unittest.TestCase):
    def test_match_termine(self):
        m = {
            "event_key": 123, "event_type_type": "Atp Singles",
            "event_first_player": "A", "event_second_player": "B",
            "event_winner": "First Player", "event_final_result": "2 - 0",
            "event_status": "Finished",
            "scores": [{"score_set": "1", "score_first": "6", "score_second": "4"}],
            "tournament_name": "X", "event_date": "2026-06-01",
        }
        r = live_api._parse_result(m)
        self.assertEqual(r["winner"], "p1")
        self.assertTrue(r["finished"])
        self.assertEqual(r["tour"], "atp")
        self.assertEqual(len(r["sets"]), 1)

    def test_match_non_termine(self):
        m = {"event_key": 1, "event_winner": "", "event_status": "", "scores": []}
        r = live_api._parse_result(m)
        self.assertIsNone(r["winner"])
        self.assertFalse(r["finished"])

    def test_second_joueur_gagne(self):
        m = {"event_key": 2, "event_winner": "Second Player",
             "event_status": "Finished", "scores": [{"score_set": "1"}],
             "event_first_player": "A", "event_second_player": "B"}
        self.assertEqual(live_api._parse_result(m)["winner"], "p2")


class TestCalibrationMetrics(unittest.TestCase):
    def setUp(self):
        self._fd, self._path = tempfile.mkstemp(suffix=".db")
        self._save = config.DB_FILE
        config.DB_FILE = self._path
        db.init()

    def tearDown(self):
        config.DB_FILE = self._save
        os.close(self._fd)
        os.remove(self._path)

    def _settle(self, ek, tour, p1, winner, prob1, correct):
        db.insert_settled({
            "event_key": ek, "date": "2026-06-01", "tour": tour, "tournament": "T",
            "player1": p1, "player2": "Z", "winner": winner, "final_score": "2-0",
            "sets": [], "pred_favorite": (p1 if correct else "Z"),
            "pred_prob1": prob1, "correct": correct,
        })

    def test_aucun_match(self):
        self.assertEqual(settlement.calibration_metrics()["n"], 0)

    def test_idempotent_event_key(self):
        self.assertTrue(db.insert_settled({"event_key": "x", "winner": "A",
                                           "player1": "A", "correct": 1}))
        # même event_key -> ignoré
        self.assertFalse(db.insert_settled({"event_key": "x", "winner": "A",
                                            "player1": "A", "correct": 1}))

    def test_precision_et_segments(self):
        self._settle("1", "atp", "A", "A", 70.0, 1)   # favori clair, correct
        self._settle("2", "atp", "B", "Z", 65.0, 0)   # favori clair, raté
        self._settle("3", "wta", "C", "C", 80.0, 1)   # favori clair, correct
        m = settlement.calibration_metrics()
        self.assertEqual(m["n"], 3)
        self.assertAlmostEqual(m["accuracy"], round(2 / 3, 4))
        self.assertAlmostEqual(m["wta_acc"], 1.0)
        self.assertIsNotNone(m["brier"])
        self.assertIsNone(m["roi"])   # ROI non calculé (pas de cotes stockées)


if __name__ == "__main__":
    unittest.main()
