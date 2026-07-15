"""Tests prefetch SQLite batch pour intelligence_layer (engineer/today perf)."""
from __future__ import annotations

import os
import tempfile
import unittest

from bot import config, db, intelligence_layer


class TestPrefetchPlayerIntel(unittest.TestCase):
    def setUp(self):
        self._fd, self._path = tempfile.mkstemp(suffix=".db")
        self._save = config.DB_FILE
        config.DB_FILE = self._path
        db.init()
        with db.connect() as conn:
            conn.executemany(
                "INSERT INTO matches "
                "(id,date,tour,winner,loser,w_serve,w_return1,w_return2,"
                " l_serve,l_return1,l_return2,surface,margin) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                [
                    ("m1", "20250701", "atp", "Alice", "Bob",
                     0.6, 0.5, 0.5, 0.6, 0.5, 0.5, "hard", 2),
                    ("m2", "20250705", "atp", "Bob", "Alice",
                     0.6, 0.5, 0.5, 0.6, 0.5, 0.5, "hard", 2),
                    ("m3", "20250710", "atp", "Alice", "Carol",
                     0.6, 0.5, 0.5, 0.6, 0.5, 0.5, "hard", 2),
                ],
            )

    def tearDown(self):
        config.DB_FILE = self._save
        os.close(self._fd)
        os.remove(self._path)

    def test_prefetch_populates_records_and_h2h(self):
        cache = db.prefetch_player_intel(
            ["Alice", "Bob"], [("Alice", "Bob")],
            fatigue_cutoff="20250701",
        )
        self.assertEqual(cache.records["Alice"]["wins"], 2)
        self.assertEqual(cache.records["Alice"]["losses"], 1)
        self.assertEqual(len(cache.h2h[("Alice", "Bob")]), 2)

    def test_intel_batch_uses_cache_for_signals(self):
        mem = {"players": {"Alice": {"n": 20, "recent": 0.6},
                           "Bob": {"n": 20, "recent": 0.5}},
               "elo": {"Alice": 1600, "Bob": 1500}}
        with intelligence_layer.intel_batch(["Alice", "Bob"], [("Alice", "Bob")]):
            rec = intelligence_layer._cached_record("Alice")  # noqa: SLF001
            h2h = intelligence_layer._cached_h2h("Alice", "Bob")  # noqa: SLF001
        self.assertEqual(rec["wins"], 2)
        self.assertEqual(len(h2h), 2)
        sigs = intelligence_layer.form_signals(mem, "Alice", "Bob")
        self.assertIsInstance(sigs, list)


if __name__ == "__main__":
    unittest.main()
