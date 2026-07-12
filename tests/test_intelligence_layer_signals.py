"""Tests pour fatigue_signals/opponent_quality_signals (bot/intelligence_layer.py).

DB SQLite temporaire (pas de mock) : ces fonctions dépendent de la
normalisation REPLACE(date,'-','') pour gérer les deux formats de date
mélangés dans matches.date ("20220103" vs "2022-01-17", confirmé 87%/13%
sur les 91946 lignes réelles) — un mock de db.connect() masquerait
justement le bug qu'on cherche à couvrir ici.
"""
from __future__ import annotations

import datetime as _dt
import os
import tempfile
import unittest

from bot import config, db, intelligence_layer as il


class SignalsTestCase(unittest.TestCase):
    def setUp(self):
        self._fd, self._path = tempfile.mkstemp(suffix=".db")
        self._save = config.DB_FILE
        config.DB_FILE = self._path
        db.init()

    def tearDown(self):
        config.DB_FILE = self._save
        os.close(self._fd)
        os.remove(self._path)

    def _insert_match(self, date: str, winner: str, loser: str):
        with db.connect() as conn:
            conn.execute(
                "INSERT INTO matches (date,tour,winner,loser,w_serve,w_return1,w_return2,"
                "l_serve,l_return1,l_return2,surface,margin) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (date, "atp", winner, loser, 0.6, 0.5, 0.5, 0.5, 0.5, 0.5, "hard", 0),
            )


class TestFatigueSignal(SignalsTestCase):
    def test_no_signal_below_threshold(self):
        today = _dt.date.today().strftime("%Y%m%d")
        for i in range(3):  # sous FATIGUE_MATCH_THRESHOLD (6)
            self._insert_match(today, "Alice", f"Opp{i}")
        self.assertEqual(il.fatigue_signals("Alice", "Bob"), [])

    def test_flags_player_with_many_recent_matches_dashed_format(self):
        recent = _dt.date.today().strftime("%Y-%m-%d")  # format AVEC tirets
        for i in range(7):
            self._insert_match(recent, "Alice", f"Opp{i}")
        signals = il.fatigue_signals("Alice", "Bob")
        self.assertEqual(len(signals), 1)
        self.assertEqual(signals[0]["player"], "Alice")
        self.assertGreaterEqual(signals[0]["matches_recent"], 6)

    def test_flags_player_with_many_recent_matches_compact_format(self):
        recent = _dt.date.today().strftime("%Y%m%d")  # format SANS tirets (Sackmann)
        for i in range(7):
            self._insert_match(recent, "Alice", f"Opp{i}")
        signals = il.fatigue_signals("Alice", "Bob")
        self.assertEqual(len(signals), 1)

    def test_ignores_matches_outside_window(self):
        old_date = (_dt.date.today() - _dt.timedelta(days=60)).strftime("%Y%m%d")
        for i in range(7):
            self._insert_match(old_date, "Alice", f"Opp{i}")
        self.assertEqual(il.fatigue_signals("Alice", "Bob"), [])

    def test_mixed_date_formats_both_counted_correctly(self):
        """Le bug qu'on évite : sans normalisation, comparer "2026-07-01" à
        un cutoff "20260628" (chaînes de longueurs différentes) est faux."""
        recent_dashed = _dt.date.today().strftime("%Y-%m-%d")
        recent_compact = _dt.date.today().strftime("%Y%m%d")
        for i in range(4):
            self._insert_match(recent_dashed, "Alice", f"OppA{i}")
        for i in range(4):
            self._insert_match(recent_compact, "Alice", f"OppB{i}")
        signals = il.fatigue_signals("Alice", "Bob")
        self.assertEqual(signals[0]["matches_recent"], 8)


class TestOpponentQualitySignal(SignalsTestCase):
    def _mem(self, elo: dict):
        return {"elo": elo}

    def test_no_signal_with_too_few_matches(self):
        today = _dt.date.today().strftime("%Y%m%d")
        for i in range(3):  # sous OPPONENT_QUALITY_MIN_MATCHES (5)
            self._insert_match(today, "Alice", f"Opp{i}")
        mem = self._mem({"Alice": 1500})
        self.assertEqual(il.opponent_quality_signals(mem, "Alice", "Bob"), [])

    def test_flags_weaker_recent_opponents(self):
        today = _dt.date.today().strftime("%Y%m%d")
        for i in range(6):
            self._insert_match(today, "Alice", f"Weak{i}")
        elo = {"Alice": 2000.0, **{f"Weak{i}": 1400.0 for i in range(6)}}
        signals = il.opponent_quality_signals(self._mem(elo), "Alice", "Bob")
        self.assertEqual(len(signals), 1)
        self.assertEqual(signals[0]["direction"], "adversaires plus faibles que lui")

    def test_flags_stronger_recent_opponents(self):
        today = _dt.date.today().strftime("%Y%m%d")
        for i in range(6):
            self._insert_match(today, f"Strong{i}", "Alice")
        elo = {"Alice": 1500.0, **{f"Strong{i}": 2100.0 for i in range(6)}}
        signals = il.opponent_quality_signals(self._mem(elo), "Alice", "Bob")
        self.assertEqual(len(signals), 1)
        self.assertEqual(signals[0]["direction"], "adversaires plus forts que lui")

    def test_no_signal_when_elo_comparable(self):
        today = _dt.date.today().strftime("%Y%m%d")
        for i in range(6):
            self._insert_match(today, "Alice", f"Similar{i}")
        elo = {"Alice": 1550.0, **{f"Similar{i}": 1520.0 for i in range(6)}}
        self.assertEqual(il.opponent_quality_signals(self._mem(elo), "Alice", "Bob"), [])

    def test_no_signal_without_own_elo(self):
        today = _dt.date.today().strftime("%Y%m%d")
        for i in range(6):
            self._insert_match(today, "Alice", f"Opp{i}")
        self.assertEqual(il.opponent_quality_signals(self._mem({}), "Alice", "Bob"), [])


if __name__ == "__main__":
    unittest.main()
