"""Tests for bot.surface_experiment walk-forward benchmark."""
from __future__ import annotations

import os
import tempfile
import unittest

from bot import config, db
from bot.surface_experiment import (
    _brier,
    _ece,
    _logloss,
    _roi_simulated,
    run_benchmark,
)


def _synth_matches(n: int, start_year: int = 2020) -> list:
    """Synthetic chronological matches with surface for fast unit tests."""
    out = []
    surfaces = ("hard", "clay", "grass")
    players = [f"P{i}" for i in range(20)]
    for i in range(n):
        w, l = players[i % 20], players[(i + 7) % 20]
        if w == l:
            l = players[(i + 3) % 20]
        out.append({
            "id": i,
            "date": f"{start_year + i // 200:04d}{(i % 12) + 1:02d}{(i % 28) + 1:02d}",
            "tour": "atp",
            "winner_name": w,
            "loser_name": l,
            "winner": {"serve": 0.55, "return1": 0.45, "return2": 0.45},
            "loser": {"serve": 0.45, "return1": 0.55, "return2": 0.55},
            "surface": surfaces[i % 3],
            "margin": 2,
        })
    return out


class TestMetrics(unittest.TestCase):
    def test_logloss_perfect(self):
        self.assertAlmostEqual(_logloss([0.99, 0.01], [1, 0]), 0.01, delta=0.02)

    def test_brier_zero_for_perfect(self):
        self.assertAlmostEqual(_brier([1.0, 0.0], [1, 0]), 0.0)

    def test_ece_bounded(self):
        self.assertGreaterEqual(_ece([0.6, 0.4], [1, 0]), 0.0)

    def test_roi_sim_with_edge(self):
        roi = _roi_simulated([0.7, 0.3], [1, 0], [2.0, 2.0], min_edge=0.0)
        self.assertIsNotNone(roi)


class TestRunBenchmark(unittest.TestCase):
    def setUp(self):
        # run_benchmark() appelle inconditionnellement db.historical_odds_index()
        # même quand `matches` est fourni directement (skip du chemin
        # db.matches_for_backtest()) — DB temporaire avec schéma requise
        # (sinon "no such table: historical_odds" sur un checkout CI neuf).
        fd, self._path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        self._save_db_file = config.DB_FILE
        config.DB_FILE = self._path
        db.init()

    def tearDown(self):
        config.DB_FILE = self._save_db_file
        for p in (self._path, self._path + "-wal", self._path + "-shm"):
            if os.path.exists(p):
                os.remove(p)

    def test_runs_on_synthetic_data(self):
        matches = _synth_matches(800)
        report = run_benchmark(matches, min_test=100, write_report=False)
        self.assertTrue(report.get("fitted"))
        self.assertIn("baseline", report)
        self.assertIn("enhanced", report)
        self.assertIn("delta", report)

    def test_insufficient_data_returns_note(self):
        report = run_benchmark(_synth_matches(50), min_test=500, write_report=False)
        self.assertFalse(report.get("fitted"))


if __name__ == "__main__":
    unittest.main()
