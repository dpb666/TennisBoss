"""Tests pour bot/market_efficiency_audit.py — mécanique des fonctions
(structure de sortie, garde-fous n insuffisant), pas les chiffres réels de
prod (ceux-là sont dans docs/MARKET_EFFICIENCY_AUDIT.md, obtenus en lecture
seule sur la DB de prod).
"""
from __future__ import annotations

import os
import tempfile
import unittest

from bot import config, db, market_efficiency_audit as mea


class MarketEfficiencyTestCase(unittest.TestCase):
    def setUp(self):
        self._fd, self._path = tempfile.mkstemp(suffix=".db")
        self._save = config.DB_FILE
        config.DB_FILE = self._path
        db.init()

    def tearDown(self):
        config.DB_FILE = self._save
        os.close(self._fd)
        os.remove(self._path)

    def _insert_settled_and_bet(self, i, won, fav_odds=2.0, pred_prob1=60.0):
        db.insert_settled({
            "event_key": f"e{i}", "date": f"2026-0{(i % 9) + 1}-01", "tour": "atp",
            "player1": f"P{i}", "player2": f"Q{i}",
            "winner": f"P{i}" if won else f"Q{i}",
            "pred_favorite": f"P{i}", "pred_prob1": pred_prob1,
            "correct": 1 if won else 0,
        })
        with db.connect() as conn:
            conn.execute(
                "INSERT INTO bet_log (date, player1, player2, favorite, fav_odds, ts) "
                "VALUES (?,?,?,?,?,?)",
                (f"2026-0{(i % 9) + 1}-01", f"P{i}", f"Q{i}", f"P{i}", fav_odds, "2026-01-01T00:00:00"),
            )


class TestAuditMarketBlendZero(MarketEfficiencyTestCase):
    def test_insufficient_samples_returns_note(self):
        result = mea.audit_market_blend_zero()
        self.assertIn("note", result)

    def test_runs_end_to_end_with_enough_samples(self):
        for i in range(40):
            won = i % 3 == 0  # modèle prédit 60% mais ne gagne que ~33% -> surconfiant
            self._insert_settled_and_bet(i, won)
        result = mea.audit_market_blend_zero()
        self.assertIn("by_calibration_level", result)
        for label in ("raw_k1.0", "stored_calib_k", "refit_temperature_k"):
            self.assertIn(label, result["by_calibration_level"])
        self.assertIn("logloss_curve_w_0_to_1", result)
        self.assertEqual(len(result["logloss_curve_w_0_to_1"]), 21)
        self.assertIn("model_market_correlation", result)
        self.assertIn("verdict", result)


class TestMarketDisagreementAnalysis(MarketEfficiencyTestCase):
    def test_empty_db_all_buckets_zero(self):
        result = mea.market_disagreement_analysis()
        self.assertEqual(result["n_total"], 0)
        self.assertTrue(all(b["n"] == 0 for b in result["buckets"]))

    def test_buckets_sum_to_total(self):
        for i in range(30):
            won = i % 2 == 0
            self._insert_settled_and_bet(i, won, fav_odds=1.8, pred_prob1=65.0)
        result = mea.market_disagreement_analysis(calib_k=1.0)
        total_bucketed = sum(b["n"] for b in result["buckets"])
        self.assertEqual(total_bucketed, result["n_total"])


class TestClvByConfidenceDetailed(MarketEfficiencyTestCase):
    def _insert_bet_history(self, i, confidence, result, profit_loss):
        db.log_bet_history({
            "event_key": f"bh{i}", "player1": f"P{i}", "player2": f"Q{i}",
            "date": "2026-01-01", "prediction": 0.6, "pick_side": f"P{i}",
            "odds": 2.0, "confidence": confidence, "result": result,
            "profit_loss": profit_loss, "clv_pct": 0.0, "surface": "hard",
        })

    def test_empty_returns_empty_bins(self):
        result = mea.clv_by_confidence_detailed()
        self.assertTrue(all(b["n"] == 0 for b in result["bins"]))
        self.assertFalse(result["hypothesis_high_conf_worst_clv_confirmed"])

    def test_rejects_hypothesis_when_cis_overlap(self):
        # Même taux de victoire (bruit) dans toutes les tranches de confiance
        # -> les IC se chevauchent forcément -> hypothèse rejetée.
        for i in range(60):
            conf = [0.3, 0.65, 0.8, 0.9][i % 4]
            won = 1 if i % 3 == 0 else 0
            self._insert_bet_history(i, conf, won, (1.0 if won else -1.0))
        result = mea.clv_by_confidence_detailed()
        self.assertFalse(result["hypothesis_high_conf_worst_clv_confirmed"])
        self.assertIn("NON CONFIRMÉE", result["verdict"])


class TestValueBetEvAudit(MarketEfficiencyTestCase):
    def test_empty_returns_zero_total(self):
        result = mea.value_bet_ev_audit()
        self.assertEqual(result["n_total"], 0)

    def test_buckets_partition_by_predicted_ev(self):
        with db.connect() as conn:
            for i in range(20):
                conn.execute(
                    "INSERT INTO bet_history (event_key,player1,player2,date,odds,result,"
                    "profit_loss,confidence,surface) VALUES (?,?,?,?,?,?,?,?,?)",
                    (f"bh{i}", f"P{i}", f"Q{i}", "2026-01-01", 2.0, i % 2, (1.0 if i % 2 else -1.0), 0.6, "hard"),
                )
                conn.execute(
                    "INSERT INTO clv_log (event_key,date,player1,player2,pick_side,pick_odds,"
                    "pick_prob,confidence,pick_ts,result) VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (f"bh{i}", "2026-01-01", f"P{i}", f"Q{i}", f"P{i}", 2.0, 0.55, 0.6, "2026-01-01", i % 2),
                )
        result = mea.value_bet_ev_audit()
        self.assertEqual(result["n_total"], 20)
        total_bucketed = sum(b["n"] for b in result["buckets"])
        self.assertEqual(total_bucketed, 20)


class TestSegmentationReport(MarketEfficiencyTestCase):
    def test_empty_db(self):
        result = mea.segmentation_report()
        self.assertEqual(result["n_total"], 0)
        self.assertFalse(result["tournament_level"]["available"])
        self.assertFalse(result["ranking_diff"]["available"])

    def test_surface_and_odds_segmentation_covers_all_rows(self):
        with db.connect() as conn:
            for i in range(15):
                surf = ["hard", "clay", "grass", ""][i % 4]
                conn.execute(
                    "INSERT INTO bet_history (event_key,player1,player2,date,odds,result,"
                    "profit_loss,confidence,surface) VALUES (?,?,?,?,?,?,?,?,?)",
                    (f"bh{i}", f"P{i}", f"Q{i}", "2026-01-01", 2.2, i % 2,
                     (1.2 if i % 2 else -1.0), 0.65, surf),
                )
        result = mea.segmentation_report()
        self.assertEqual(result["n_total"], 15)
        n_by_surface = sum(v.get("n", 0) for v in result["by_surface"].values())
        self.assertEqual(n_by_surface, 15)


if __name__ == "__main__":
    unittest.main()
