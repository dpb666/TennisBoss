"""Tests pour bot/signal_backtest.py — backtest walk-forward des signaux
Sport Intelligence Layer (calib_k, form_signal, steam_move).

DB SQLite temporaire (même pattern que test_settlement.py) : ces fonctions
font des requêtes SQL réelles sur settled_matches/matches/market_snapshots,
pas mockables proprement.
"""
from __future__ import annotations

import os
import tempfile
import unittest

from bot import config, db, signal_backtest as sb


class SignalBacktestTestCase(unittest.TestCase):
    def setUp(self):
        self._fd, self._path = tempfile.mkstemp(suffix=".db")
        self._save = config.DB_FILE
        config.DB_FILE = self._path
        db.init()

    def tearDown(self):
        config.DB_FILE = self._save
        os.close(self._fd)
        os.remove(self._path)


class TestBacktestCalibration(SignalBacktestTestCase):
    def _insert_settled(self, n: int, date_prefix: str, favorite_win_rate: float, pred_prob1: float):
        """Insère n matchs où `favorite_win_rate` fraction ont winner==player1."""
        for i in range(n):
            won = i < int(n * favorite_win_rate)
            db.insert_settled({
                "event_key": f"{date_prefix}-{i}", "date": f"{date_prefix}-{i:04d}"[:10] or date_prefix,
                "tour": "atp", "player1": f"P{i}", "player2": f"Q{i}",
                "winner": f"P{i}" if won else f"Q{i}",
                "pred_favorite": f"P{i}", "pred_prob1": pred_prob1,
                "correct": 1 if won else 0,
            })

    def test_not_enough_data_reports_unfitted(self):
        result = sb.backtest_calibration(min_test=50)
        self.assertFalse(result["fitted"])

    def test_overconfident_predictions_get_calibrated_down(self):
        # 200 matchs à date factice, modèle prédit 90% mais le favori ne gagne
        # que ~55% du temps -> sur-confiant, log-loss brute élevée.
        for i in range(200):
            date = f"2026-01-{(i % 28) + 1:02d}"
            won = i % 20 < 11  # ~55%
            db.insert_settled({
                "event_key": f"e{i}", "date": date, "tour": "atp",
                "player1": f"P{i}", "player2": f"Q{i}",
                "winner": f"P{i}" if won else f"Q{i}",
                "pred_favorite": f"P{i}", "pred_prob1": 90.0,
                "correct": 1 if won else 0,
            })
        result = sb.backtest_calibration(test_fraction=0.3, min_test=10)
        self.assertTrue(result["fitted"])
        # La calibration doit réduire la log-loss hors-échantillon vs le brut sur-confiant.
        self.assertLess(result["logloss_temperature"], result["logloss_raw"])


class TestBacktestFormSignal(SignalBacktestTestCase):
    def _insert_match(self, date, winner, loser, w_serve=0.6, l_serve=0.5):
        with db.connect() as conn:
            conn.execute(
                "INSERT INTO matches (date,tour,winner,loser,w_serve,w_return1,w_return2,"
                "l_serve,l_return1,l_return2,surface,margin) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (date, "atp", winner, loser, w_serve, 0.5, 0.5, l_serve, 0.5, 0.5, "hard", 0),
            )

    def test_empty_db_returns_zero_matches(self):
        result = sb.backtest_form_signal()
        self.assertEqual(result["n_matches_replayed"], 0)

    def test_replays_matches_without_error_and_buckets_appearances(self):
        # 30 matchs "Alice" vs adversaires variés, dates croissantes.
        for i in range(30):
            self._insert_match(f"2026-01-{(i % 28) + 1:02d}", "Alice", f"Opp{i}")
        result = sb.backtest_form_signal(min_matches=5)
        total_appearances = (result["surperformance"]["total"] + result["méforme"]["total"]
                             + result["aucun_signal"]["total"])
        self.assertEqual(total_appearances, 60)  # 30 matchs x 2 apparitions (gagnant+perdant)


class TestBacktestSteamMove(SignalBacktestTestCase):
    def test_no_data_returns_zero(self):
        result = sb.backtest_steam_move()
        self.assertEqual(result["n_with_move"], 0)

    def test_detects_real_steam_move_and_computes_edge(self):
        db.insert_settled({
            "event_key": "e1", "date": "2026-07-01", "tour": "atp",
            "player1": "A", "player2": "B", "winner": "A",
        })
        # Cote A raccourcit de 3.0 -> 2.0 (steam move réel, > seuil 15%).
        db.record_market_snapshot("e1", "A", "B", odds_home=3.0, odds_away=1.5, hours_ahead=5.0)
        db.record_market_snapshot("e1", "A", "B", odds_home=2.0, odds_away=2.0, hours_ahead=1.0)
        result = sb.backtest_steam_move(threshold_pct=15.0)
        self.assertEqual(result["n_with_move"], 1)
        self.assertEqual(result["actual_win_rate_moved_side"], 1.0)  # A a gagné

    def test_ignores_a_lengthening_odds_move(self):
        db.insert_settled({
            "event_key": "e2", "date": "2026-07-01", "tour": "atp",
            "player1": "A", "player2": "B", "winner": "B",
        })
        # Cote A s'ALLONGE (2.0 -> 3.0, +50%) : ce n'est PAS un steam move sur A.
        db.record_market_snapshot("e2", "A", "B", odds_home=2.0, odds_away=1.8, hours_ahead=5.0)
        db.record_market_snapshot("e2", "A", "B", odds_home=3.0, odds_away=1.4, hours_ahead=1.0)
        result = sb.backtest_steam_move(threshold_pct=15.0)
        self.assertEqual(result["n_with_move"], 1)  # le côté B (away) a bien raccourci
        self.assertEqual(result["actual_win_rate_moved_side"], 1.0)  # B a gagné


if __name__ == "__main__":
    unittest.main()
