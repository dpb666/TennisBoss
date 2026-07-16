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


class TestProportionZtest(unittest.TestCase):
    """Test de proportion (bot.signal_backtest._proportion_ztest) — isolé de
    la replay DB pour vérifier la formule elle-même avec des valeurs
    connues/vérifiables à la main."""

    def test_exactly_at_null_gives_zero_z_and_p_one(self):
        z, p = sb._proportion_ztest(0.5, 1000)
        self.assertEqual(z, 0.0)
        self.assertEqual(p, 1.0)

    def test_matches_observed_production_values(self):
        # Valeurs réellement observées sur les données de prod (2026-07-15) :
        # rate=0.5298, n=1357 -> z≈2.196, p≈0.028 (significatif à 95%).
        z, p = sb._proportion_ztest(0.5298, 1357)
        self.assertAlmostEqual(z, 2.196, delta=0.005)
        self.assertLess(p, 0.05)

    def test_zero_n_returns_none(self):
        z, p = sb._proportion_ztest(0.6, 0)
        self.assertIsNone(z)
        self.assertIsNone(p)

    def test_far_from_null_is_highly_significant(self):
        z, p = sb._proportion_ztest(0.9, 500)
        self.assertGreater(abs(z), 10)
        self.assertLess(p, 0.001)


class TestBacktestClutchVsElo(SignalBacktestTestCase):
    def _insert_match(self, date, winner, loser, w_bp_saved, w_bp_faced,
                      l_bp_saved, l_bp_faced, margin=0):
        with db.connect() as conn:
            conn.execute(
                "INSERT INTO matches (date,tour,winner,loser,w_serve,w_return1,w_return2,"
                "l_serve,l_return1,l_return2,surface,margin,"
                "w_bp_saved,w_bp_faced,l_bp_saved,l_bp_faced)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (date, "atp", winner, loser, 0.6, 0.5, 0.5, 0.6, 0.5, 0.5, "hard", margin,
                 w_bp_saved, w_bp_faced, l_bp_saved, l_bp_faced),
            )

    def test_empty_db_returns_zero_matches(self):
        result = sb.backtest_clutch_vs_elo()
        self.assertEqual(result["n_evaluated_all"], 0)

    def test_elo_close_subset_never_exceeds_full_subset(self):
        # Constitue un historique BP pour 20 joueurs (10 "haut" taux de BP
        # sauvées, 10 "bas") via des matchs neutres, puis évalue des duels
        # haut-vs-bas : le sous-ensemble ELO-proche doit toujours être un
        # sous-ensemble (jamais plus grand) de l'ensemble évalué, et la
        # structure de sortie doit être complète, quel que soit le résultat
        # numérique exact (qui dépend de la dynamique ELO réelle rejouée).
        for i in range(10):
            hi, lo = f"Hi{i}", f"Lo{i}"
            filler_hi, filler_lo = f"FHi{i}", f"FLo{i}"
            # Hi{i} accumule un bon taux de BP sauvées (16/20 = 80%).
            self._insert_match(f"2026-01-{i+1:02d}", hi, filler_hi, 16, 20, 10, 20)
            # Lo{i} accumule un mauvais taux de BP sauvées (4/20 = 20%).
            self._insert_match(f"2026-01-{i+1:02d}", filler_lo, lo, 10, 20, 4, 20)
        for i in range(10):
            # Match évalué : Hi{i} vs Lo{i}, écart BP net >= diff_threshold.
            self._insert_match(f"2026-02-{i+1:02d}", f"Hi{i}", f"Lo{i}", 5, 10, 5, 10)

        result = sb.backtest_clutch_vs_elo(min_bp_faced=15, diff_threshold=0.08)

        for key in ("elo_close_threshold", "min_bp_faced", "diff_threshold",
                    "n_evaluated_all", "clutch_win_rate_all", "n_evaluated_elo_close",
                    "clutch_win_rate_elo_close", "avg_elo_gap_evaluated",
                    "z_score", "p_value_approx", "significant_95pct", "baseline", "verdict"):
            self.assertIn(key, result)

        self.assertGreaterEqual(result["n_evaluated_all"], 1)
        self.assertLessEqual(result["n_evaluated_elo_close"], result["n_evaluated_all"])
        if result["n_evaluated_elo_close"]:
            self.assertGreaterEqual(result["clutch_win_rate_elo_close"], 0.0)
            self.assertLessEqual(result["clutch_win_rate_elo_close"], 1.0)


if __name__ == "__main__":
    unittest.main()
