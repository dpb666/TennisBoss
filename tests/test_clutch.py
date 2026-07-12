"""Tests de la couche "clutch" (break points / tie-breaks) :
parsing Sackmann (datasource), agrégats DB, signal informationnel
(intelligence_layer) et backtest walk-forward (signal_backtest).

DB SQLite temporaire réelle pour les parties SQL (normalisation de date,
agrégation NULL-safe) — même pattern que test_intelligence_layer_signals.py.
"""
from __future__ import annotations

import os
import tempfile
import unittest

from bot import config, datasource, db, intelligence_layer as il, signal_backtest


class TestParseTiebreaks(unittest.TestCase):
    def test_no_tiebreak(self):
        self.assertEqual(datasource.parse_tiebreaks("6-4 6-3"), (0, 0))

    def test_winner_and_loser_tiebreaks(self):
        # Vainqueur gagne les sets 1 et 3 (TB), perdant gagne le set 2 (TB).
        self.assertEqual(datasource.parse_tiebreaks("7-6(5) 6-7(3) 7-6(10)"), (2, 1))

    def test_super_tiebreak_bracket(self):
        self.assertEqual(datasource.parse_tiebreaks("6-4 4-6 [10-7]"), (1, 0))

    def test_walkover_returns_none(self):
        self.assertEqual(datasource.parse_tiebreaks(""), (None, None))
        self.assertEqual(datasource.parse_tiebreaks("   "), (None, None))

    def test_retirement_mid_match_ignores_garbage(self):
        self.assertEqual(datasource.parse_tiebreaks("7-6(4) 2-1 RET"), (1, 0))

    def test_match_features_extracts_bp_and_tb(self):
        row = {
            "tourney_id": "t1", "match_num": "1", "tourney_date": "20240101",
            "winner_name": "Alice", "loser_name": "Bob",
            "score": "7-6(2) 6-4", "surface": "Hard", "tourney_name": "Test Open",
            "w_svpt": "80", "w_1stIn": "50", "w_1stWon": "40", "w_2ndWon": "15",
            "l_svpt": "75", "l_1stIn": "45", "l_1stWon": "30", "l_2ndWon": "12",
            "w_bpSaved": "5", "w_bpFaced": "7", "l_bpSaved": "3", "l_bpFaced": "8",
        }
        m = datasource._match_features(row)
        self.assertEqual(m["w_bp_saved"], 5.0)
        self.assertEqual(m["w_bp_faced"], 7.0)
        self.assertEqual(m["l_bp_saved"], 3.0)
        self.assertEqual(m["l_bp_faced"], 8.0)
        self.assertEqual(m["w_tb_won"], 1)
        self.assertEqual(m["l_tb_won"], 0)

    def test_match_features_tolerates_missing_bp(self):
        row = {
            "tourney_id": "t1", "match_num": "1", "tourney_date": "20240101",
            "winner_name": "Alice", "loser_name": "Bob",
            "score": "6-4 6-4", "surface": "Clay", "tourney_name": "Test",
            "w_svpt": "80", "w_1stIn": "50", "w_1stWon": "40", "w_2ndWon": "15",
            "l_svpt": "75", "l_1stIn": "45", "l_1stWon": "30", "l_2ndWon": "12",
        }
        m = datasource._match_features(row)
        self.assertIsNone(m["w_bp_saved"])
        self.assertEqual(m["w_tb_won"], 0)


class ClutchDbTestCase(unittest.TestCase):
    def setUp(self):
        self._fd, self._path = tempfile.mkstemp(suffix=".db")
        self._save = config.DB_FILE
        config.DB_FILE = self._path
        db.init()

    def tearDown(self):
        config.DB_FILE = self._save
        os.close(self._fd)
        os.remove(self._path)

    def _insert(self, mid: str, date: str, winner: str, loser: str,
                w_bp=(0, 0), l_bp=(0, 0), tb=(0, 0), with_bp: bool = True):
        with db.connect() as conn:
            conn.execute(
                "INSERT INTO matches (id,date,tour,winner,loser,w_serve,w_return1,"
                "w_return2,l_serve,l_return1,l_return2,surface,margin,"
                "w_bp_saved,w_bp_faced,l_bp_saved,l_bp_faced,w_tb_won,l_tb_won) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (mid, date, "atp", winner, loser, 0.6, 0.5, 0.5, 0.5, 0.5, 0.5,
                 "hard", 2,
                 w_bp[0] if with_bp else None, w_bp[1] if with_bp else None,
                 l_bp[0] if with_bp else None, l_bp[1] if with_bp else None,
                 tb[0], tb[1]),
            )


class TestPlayerClutchStats(ClutchDbTestCase):
    def test_aggregates_both_sides(self):
        # Alice gagne (5/7 BP sauvées, adversaire 3/8) puis perd (2/4, adv 6/6).
        self._insert("m1", "20240101", "Alice", "Bob", w_bp=(5, 7), l_bp=(3, 8), tb=(1, 0))
        self._insert("m2", "20240201", "Carol", "Alice", w_bp=(6, 6), l_bp=(2, 4), tb=(0, 1))
        s = db.player_clutch_stats("Alice", 20)
        self.assertEqual(s["n_matches"], 2.0)
        self.assertEqual(s["bp_saved"], 7.0)      # 5 + 2
        self.assertEqual(s["bp_faced"], 11.0)     # 7 + 4
        # Converties = BP non sauvées par l'adversaire : (8-3) + (6-6) = 5
        self.assertEqual(s["bp_converted"], 5.0)
        self.assertEqual(s["bp_chances"], 14.0)   # 8 + 6
        self.assertEqual(s["tb_won"], 2.0)        # TB gagné dans m1 (côté W) et m2 (côté L)
        self.assertEqual(s["tb_played"], 2.0)

    def test_ignores_rows_without_bp_stats(self):
        self._insert("m1", "20240101", "Alice", "Bob", with_bp=False)
        s = db.player_clutch_stats("Alice", 20)
        self.assertEqual(s["n_matches"], 0.0)

    def test_window_respects_normalized_date_order(self):
        # Le match le plus ANCIEN a un format compact, le plus récent des tirets :
        # avec limit=1 on ne doit garder que le plus récent (2025).
        self._insert("m1", "20200101", "Alice", "Bob", w_bp=(10, 10))
        self._insert("m2", "2025-06-01", "Alice", "Carol", w_bp=(1, 5))
        s = db.player_clutch_stats("Alice", 1)
        self.assertEqual(s["bp_faced"], 5.0)


class TestClutchSignal(ClutchDbTestCase):
    def test_flags_strong_bp_saver(self):
        # 3 matchs, 18/24 BP sauvées = 0.75 >= seuil haut (0.72).
        for i, (s_, f_) in enumerate(((6, 8), (6, 8), (6, 8))):
            self._insert(f"m{i}", f"2024010{i + 1}", "Alice", f"Opp{i}", w_bp=(s_, f_))
        sig = il._clutch_signal("Alice")
        self.assertIsNotNone(sig)
        self.assertIn("solide sur balles de break", sig["direction"])
        self.assertEqual(sig["bp_save_rate"], 0.75)

    def test_flags_weak_tiebreaker(self):
        # 6 TB joués, 1 gagné = 0.167 <= seuil bas (0.30). BP sous l'échantillon min.
        for i in range(3):
            self._insert(f"m{i}", f"2024010{i + 1}", f"Opp{i}", "Alice",
                         w_bp=(1, 2), l_bp=(1, 2), tb=(2, 0) if i else (1, 1))
        sig = il._clutch_signal("Alice")
        self.assertIsNotNone(sig)
        self.assertIn("faible en tie-break", sig["direction"])

    def test_no_signal_below_sample_thresholds(self):
        self._insert("m1", "20240101", "Alice", "Bob", w_bp=(2, 3), tb=(1, 0))
        self.assertIsNone(il._clutch_signal("Alice"))

    def test_no_signal_when_rates_ordinary(self):
        # 0.625 de BP sauvées, 0.5 de TB : dans la norme -> pas de signal.
        for i in range(4):
            self._insert(f"m{i}", f"2024010{i + 1}", "Alice", f"Opp{i}",
                         w_bp=(5, 8), tb=(1, 1))
        self.assertIsNone(il._clutch_signal("Alice"))

    def test_clutch_signals_wrapper_both_players(self):
        for i in range(3):
            self._insert(f"m{i}", f"2024010{i + 1}", "Alice", f"Opp{i}", w_bp=(6, 8))
        sigs = il.clutch_signals("Alice", "Bob")
        self.assertEqual(len(sigs), 1)
        self.assertEqual(sigs[0]["player"], "Alice")


class TestBacktestClutch(ClutchDbTestCase):
    def test_walk_forward_no_leakage_and_direction(self):
        # Historique : Alice très clutch (9/10 par match), Bob fragile (2/10).
        # 4 matchs d'historique chacun (vs des tiers), puis 3 duels Alice-Bob
        # gagnés par Alice -> le côté "plus clutch" gagne 100% des évaluations.
        for i in range(4):
            self._insert(f"a{i}", f"2023010{i + 1}", "Alice", f"X{i}", w_bp=(9, 10), l_bp=(5, 10))
            self._insert(f"b{i}", f"2023020{i + 1}", f"Y{i}", "Bob", w_bp=(5, 10), l_bp=(2, 10))
        for i in range(3):
            self._insert(f"d{i}", f"2024010{i + 1}", "Alice", "Bob", w_bp=(5, 6), l_bp=(2, 6))
        r = signal_backtest.backtest_clutch(min_bp_faced=20, diff_threshold=0.05)
        self.assertEqual(r["n_evaluated"], 3)
        self.assertEqual(r["clutch_side_win_rate"], 1.0)

    def test_empty_archive_returns_note(self):
        r = signal_backtest.backtest_clutch()
        self.assertEqual(r["n_evaluated"], 0)
        self.assertIn("note", r)


if __name__ == "__main__":
    unittest.main()
