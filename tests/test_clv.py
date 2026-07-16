"""Tests CLV : closing line value, P&L flat/Kelly, fallback, verdict."""
import os
import tempfile
import unittest

from bot import clv, config, db


class TestCLV(unittest.TestCase):
    def setUp(self):
        self._fd, self._path = tempfile.mkstemp(suffix=".db")
        self._save = config.DB_FILE
        config.DB_FILE = self._path
        db.init()

    def tearDown(self):
        config.DB_FILE = self._save
        os.close(self._fd)
        os.remove(self._path)

    def test_clv_beat_closing(self):
        # Pick @1.80, closing @1.65 -> on a verrouillé un meilleur prix.
        clv.seed_pick("e1", "2026-06-26", "A", "B", "A", 1.80, 0.60, 0.70)
        clv.refresh_closing("e1", "A", "A", 1.65, 2.30)
        self.assertTrue(clv.settle("A", "B", "A"))
        row = db.list_clv()[0]
        self.assertEqual(row["beat_closing"], 1)
        self.assertAlmostEqual(row["clv_pct"], round((1.80 / 1.65 - 1) * 100, 2))
        self.assertEqual(row["closing_src"], "snapshot")
        self.assertEqual(row["result"], 1)
        self.assertAlmostEqual(row["pnl_flat"], 0.80)  # gagné @1.80

    def test_fallback_last_seen_when_no_closing(self):
        clv.seed_pick("e2", "2026-06-26", "C", "D", "C", 2.10, 0.52, 0.55)
        clv.settle("C", "D", "D")  # perdu, aucune closing captée
        row = db.list_clv()[0]
        self.assertEqual(row["closing_src"], "last_seen")
        self.assertEqual(row["clv_pct"], 0.0)
        self.assertEqual(row["beat_closing"], 0)
        self.assertAlmostEqual(row["pnl_flat"], -1.0)

    def test_seed_idempotent_keeps_first_odds(self):
        clv.seed_pick("e3", "2026-06-26", "E", "F", "E", 2.00, 0.55, 0.6)
        clv.seed_pick("e3", "2026-06-26", "E", "F", "E", 1.50, 0.55, 0.6)
        self.assertEqual(db.list_clv()[0]["pick_odds"], 2.00)

    def test_refresh_takes_latest_quote(self):
        clv.seed_pick("e4", "2026-06-26", "G", "H", "G", 2.00, 0.55, 0.6)
        clv.refresh_closing("e4", "G", "G", 1.90, 2.0)
        clv.refresh_closing("e4", "G", "G", 1.70, 2.4)  # dernier quote = closing
        clv.settle("G", "H", "G")
        self.assertEqual(db.list_clv()[0]["closing_odds"], 1.70)

    def test_stats_verdict_insufficient(self):
        clv.seed_pick("e5", "2026-06-26", "I", "J", "I", 1.8, 0.6, 0.7)
        clv.settle("I", "J", "I")
        self.assertEqual(clv.stats()["verdict"], "insuffisant")

    def test_settle_no_pick_returns_false(self):
        self.assertFalse(clv.settle("X", "Y", "X"))

    def test_weekly_stats_aggregates_period(self):
        clv.seed_pick("w1", "2026-07-10", "A", "B", "A", 2.0, 0.55, 0.7)
        clv.refresh_closing("w1", "A", "A", 1.85, 2.1)
        clv.settle("A", "B", "A")
        stats = clv.weekly_stats(days=30)
        self.assertEqual(stats["period_days"], 30)
        self.assertGreaterEqual(stats["global"].get("n_settled", 0), 1)
        self.assertIn("by_day", stats)

    def test_seed_pick_without_repro_still_works(self):
        # Backward compat : les appelants existants (sans `repro`) doivent
        # continuer de fonctionner, colonnes de reproductibilité NULL.
        clv.seed_pick("bc1", "2026-07-15", "K", "L", "K", 1.9, 0.58, 0.65)
        row = db.list_clv()[0]
        self.assertIsNone(row["tournament"])
        self.assertIsNone(row["model_prob_raw"])
        self.assertIsNone(row["market_disagreement"])

    def test_seed_pick_with_repro_persists_all_fields(self):
        repro = {
            "tournament": "ATP Wimbledon", "tournament_level": "grand_slam",
            "surface": "grass", "player_rank": 12.0, "opponent_rank": 45.0,
            "ranking_diff": 33.0, "model_prob_raw": 0.62, "model_prob_calibrated": 0.55,
            "market_prob": 0.50, "market_disagreement": 0.05, "ev_pct": 9.2,
            "calib_k": 0.21, "market_blend_w": 0.0, "calibration_version": "1.0",
            "predictor_version": "1.0", "feature_set_version": "1.0", "opening_odds": 2.1,
        }
        clv.seed_pick("rp1", "2026-07-15", "M", "N", "M", 2.0, 0.55, 0.7, repro=repro)
        row = db.list_clv()[0]
        for key, val in repro.items():
            self.assertEqual(row[key], val, key)


if __name__ == "__main__":
    unittest.main()
