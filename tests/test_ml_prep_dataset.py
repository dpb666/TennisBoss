"""Tests de forme pour bot/ml_prep/dataset_builder.py."""
from __future__ import annotations

import os
import tempfile
import unittest

from bot import config, db
from bot.ml_prep import FEATURE_NAMES, build_dataset
from bot.ml_prep.features import orient_players


class MlPrepDatasetTestCase(unittest.TestCase):
    def setUp(self):
        self._fd, self._path = tempfile.mkstemp(suffix=".db")
        self._save = config.DB_FILE
        config.DB_FILE = self._path
        db.init()

    def tearDown(self):
        config.DB_FILE = self._save
        os.close(self._fd)
        os.remove(self._path)

    def _insert_match(
        self,
        mid: str,
        date: str,
        winner: str,
        loser: str,
        *,
        w_serve: float = 0.65,
        l_serve: float = 0.55,
        surface: str = "hard",
    ):
        with db.connect() as conn:
            conn.execute(
                "INSERT INTO matches (id,date,tour,winner,loser,w_serve,w_return1,"
                "w_return2,l_serve,l_return1,l_return2,surface,margin) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    mid, date, "atp", winner, loser,
                    w_serve, 0.55, 0.50, l_serve, 0.45, 0.40, surface, 3,
                ),
            )

    def _insert_historical_odds(self, mid: str, date: str, winner: str, loser: str):
        with db.connect() as conn:
            conn.execute(
                "INSERT INTO historical_odds "
                "(match_id,date,tour,winner,loser,surface,psw,psl,avgw,avgl) "
                "VALUES (?,?,?,?,?,?,?,?,?,?)",
                (mid, date, "atp", winner, loser, "hard", 1.50, 2.60, 1.55, 2.45),
            )


class TestOrientPlayers(unittest.TestCase):
    def test_alphabetical_orientation(self):
        p1, p2, y = orient_players("Zoe", "Alice")
        self.assertEqual(p1, "Alice")
        self.assertEqual(p2, "Zoe")
        self.assertEqual(y, 0)

    def test_winner_is_player1(self):
        p1, p2, y = orient_players("Bob", "Alice")
        self.assertEqual(p1, "Alice")
        self.assertEqual(p2, "Bob")
        self.assertEqual(y, 0)


class TestDatasetShape(MlPrepDatasetTestCase):
    def test_build_dataset_minimum_shape(self):
        for i in range(12):
            self._insert_match(f"m{i}", f"20230{i+1:02d}01", "Alice", f"Opp{i}")
        ds = build_dataset(test_fraction=0.25, min_matches=10)
        self.assertEqual(ds.n_rows, 12)
        self.assertEqual(ds.n_train, 9)
        self.assertEqual(ds.n_test, 3)
        self.assertEqual(len(ds.feature_names), len(FEATURE_NAMES))

    def test_feature_columns_present(self):
        self._insert_match("m1", "20230101", "Alice", "Bob")
        self._insert_match("m2", "20230201", "Carol", "Dan")
        self._insert_match("m3", "20230301", "Eve", "Frank")
        self._insert_match("m4", "20230401", "Grace", "Henry")
        self._insert_match("m5", "20230501", "Ivy", "Jack")
        self._insert_match("m6", "20230601", "Kate", "Leo")
        self._insert_match("m7", "20230701", "Mia", "Noah")
        self._insert_match("m8", "20230801", "Olga", "Paul")
        self._insert_match("m9", "20230901", "Quinn", "Rita")
        self._insert_match("m10", "20231001", "Sam", "Tina")
        ds = build_dataset(test_fraction=0.2, min_matches=10)
        row = ds.rows[0]
        for name in FEATURE_NAMES:
            self.assertIn(name, row)
        self.assertIn("y", row)
        self.assertIn(row["y"], (0, 1))

    def test_matrix_dimensions(self):
        for i in range(10):
            self._insert_match(f"m{i}", f"202401{i:02d}", "Alice", f"B{i}")
        ds = build_dataset(test_fraction=0.3, min_matches=10)
        X, y, names = ds.matrix("all")
        self.assertEqual(len(X), 10)
        self.assertEqual(len(y), 10)
        self.assertEqual(len(X[0]), len(FEATURE_NAMES))
        self.assertEqual(names, FEATURE_NAMES)

    def test_historical_odds_join_increases_coverage(self):
        self._insert_match("h1", "2023-05-05", "Alice", "Bob")
        self._insert_historical_odds("h1", "2023-05-05", "Alice", "Bob")
        for i in range(9):
            self._insert_match(f"x{i}", f"202306{i:02d}", "Alice", f"X{i}")
        ds = build_dataset(test_fraction=0.2, min_matches=10)
        self.assertGreaterEqual(ds.meta["n_with_historical_odds"], 1)
        odds_rows = [r for r in ds.rows if r.get("odds_implied_p1") is not None]
        self.assertTrue(any(r["player1"] == "Alice" and r["player2"] == "Bob" for r in odds_rows))

    def test_raises_when_too_few_matches(self):
        self._insert_match("m1", "20230101", "Alice", "Bob")
        with self.assertRaises(ValueError):
            build_dataset(min_matches=10)

    def test_meta_includes_agent4_gaps(self):
        for i in range(10):
            self._insert_match(f"m{i}", f"202501{i:02d}", "Alice", f"P{i}")
        ds = build_dataset(test_fraction=0.2, min_matches=10)
        self.assertIn("needs_from_agent4", ds.meta)
        self.assertIsInstance(ds.meta["needs_from_agent4"], list)


if __name__ == "__main__":
    unittest.main()
