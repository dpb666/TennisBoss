"""Tests pour bot/decision_policy_backtest.py — mécanique walk-forward des
hypothèses A (seuil EV) et B (amortissement de désaccord). Les chiffres
réels de prod sont dans docs/EVIDENCE_DRIVEN_OPTIMIZATION.md.
"""
from __future__ import annotations

import os
import tempfile
import unittest

from bot import config, db, decision_policy_backtest as dpb


class DecisionPolicyTestCase(unittest.TestCase):
    def setUp(self):
        self._fd, self._path = tempfile.mkstemp(suffix=".db")
        self._save = config.DB_FILE
        config.DB_FILE = self._path
        db.init()

    def tearDown(self):
        config.DB_FILE = self._save
        os.close(self._fd)
        os.remove(self._path)


class TestBacktestEvThreshold(DecisionPolicyTestCase):
    def test_insufficient_data_returns_note(self):
        result = dpb.backtest_ev_threshold()
        self.assertIn("note", result)

    def test_higher_threshold_reduces_coverage_monotonically(self):
        with db.connect() as conn:
            for i in range(40):
                pick_prob = 0.3 + 0.02 * (i % 10)  # varie l'EV via la proba
                odds = 3.0
                won = 1 if i % 3 == 0 else 0
                conn.execute(
                    "INSERT INTO bet_history (event_key,player1,player2,date,odds,result,"
                    "profit_loss,confidence,surface) VALUES (?,?,?,?,?,?,?,?,?)",
                    (f"bh{i}", f"P{i}", f"Q{i}", f"2026-01-{(i % 28) + 1:02d}", odds, won,
                     (odds - 1.0 if won else -1.0), 0.6, "hard"),
                )
                conn.execute(
                    "INSERT INTO clv_log (event_key,date,player1,player2,pick_side,pick_odds,"
                    "pick_prob,confidence,pick_ts,result) VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (f"bh{i}", "2026-01-01", f"P{i}", f"Q{i}", f"P{i}", odds, pick_prob, 0.6,
                     "2026-01-01", won),
                )
        result = dpb.backtest_ev_threshold(thresholds=[0.0, 0.05, 0.10])
        coverages = [result["variants"][f"{t:.3f}"]["n"] for t in [0.0, 0.05, 0.10]
                    if result["variants"][f"{t:.3f}"].get("n")]
        self.assertEqual(coverages, sorted(coverages, reverse=True))
        self.assertIn("recommendation", result)
        self.assertIn(result["recommendation"], ("GO", "NO-GO"))


class TestBacktestDisagreementDampening(DecisionPolicyTestCase):
    def test_insufficient_data_returns_note(self):
        result = dpb.backtest_disagreement_dampening()
        self.assertIn("note", result)

    def test_runs_end_to_end_with_enough_samples(self):
        with db.connect() as conn:
            for i in range(250):
                date = f"2026-{(i % 12) + 1:02d}-{(i % 28) + 1:02d}"
                won = i % 2 == 0
                winner, loser = f"P{i}", f"Q{i}"
                pred_prob1 = 55.0 + (i % 20)  # varie le désaccord modèle/marché
                conn.execute(
                    "INSERT INTO settled_matches (event_key,date,tour,player1,player2,winner,"
                    "pred_favorite,pred_prob1,correct) VALUES (?,?,?,?,?,?,?,?,?)",
                    (f"e{i}", date, "atp", winner, loser, winner if won else loser,
                     winner, pred_prob1, 1 if won else 0),
                )
                conn.execute(
                    "INSERT INTO bet_log (date, player1, player2, favorite, fav_odds, ts) "
                    "VALUES (?,?,?,?,?,?)",
                    (date, winner, loser, winner, 2.0, "2026-01-01T00:00:00"),
                )
        result = dpb.backtest_disagreement_dampening(n_folds=3)
        self.assertIn("market_baseline", result)
        self.assertIn("variants", result)
        self.assertIn("w0.05_flat", result["variants"])
        self.assertIn("w0.05_linear_decay", result["variants"])
        self.assertIn("vs_flat_same_weight", result["variants"]["w0.05_linear_decay"])
        self.assertIn(result["recommendation"], ("GO_EXPERIMENTAL", "NO-GO"))


if __name__ == "__main__":
    unittest.main()
