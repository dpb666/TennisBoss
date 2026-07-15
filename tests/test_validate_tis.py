"""Tests pour bot/validate_tis.py (Phase 12 consolidation)."""
from __future__ import annotations

import os
import tempfile
import unittest
from unittest.mock import patch

from bot import config, db, validate_tis


class ValidateTisTestCase(unittest.TestCase):
    def setUp(self):
        self._fd, self._path = tempfile.mkstemp(suffix=".db")
        self._save = config.DB_FILE
        config.DB_FILE = self._path
        db.init()

    def tearDown(self):
        config.DB_FILE = self._save
        os.close(self._fd)
        os.remove(self._path)


class TestSanityCheck(unittest.TestCase):
    def test_valid_result_no_issues(self):
        prob = 0.58
        odds_val = 1.90
        expected_ev = round((prob * odds_val - 1.0) * 100.0, 1)
        expected_edge = round((prob - 1.0 / odds_val) * 100.0, 1)
        result = {
            "tis": 72.5,
            "categories": {"player": 30.0, "surface": 20.0, "market": 22.5},
            "model_prob": prob,
            "fair_odds": round(1 / prob, 2),
            "risk_score": 35.0,
            "recommendation": "WATCH",
            "ev_pct": expected_ev,
            "edge_pct": expected_edge,
            "favorite": "A",
            "_p1": "A",
            "_p2": "B",
        }
        odds = {"home_odds": odds_val, "away_odds": 2.05}
        self.assertEqual(validate_tis.sanity_check(result, odds), [])

    def test_detects_tis_out_of_bounds(self):
        result = {
            "tis": 105,
            "categories": {"player": 40, "surface": 30, "market": 35},
            "risk_score": 10,
            "recommendation": "NO_BET",
        }
        issues = validate_tis.sanity_check(result)
        self.assertTrue(any("tis hors bornes" in i for i in issues))

    def test_detects_fair_odds_mismatch(self):
        result = {
            "tis": 50,
            "categories": {"player": 20, "surface": 15, "market": 15},
            "model_prob": 0.60,
            "fair_odds": 2.50,
            "risk_score": 20,
            "recommendation": "NO_BET",
        }
        issues = validate_tis.sanity_check(result)
        self.assertTrue(any("fair_odds" in i for i in issues))


class TestRunValidation(ValidateTisTestCase):
    def test_run_validation_with_mock_pairs(self):
        fake_pairs = [("A", "B", "hard")] * 5
        with patch.object(validate_tis, "_sample_pairs", return_value=fake_pairs):
            with patch.object(validate_tis.memory, "load", return_value={"players": {"A": {}, "B": {}}}):
                with patch.object(validate_tis.match_intelligence, "compute_tis") as mock_tis:
                    mock_tis.return_value = {
                        "tis": 65.0,
                        "categories": {"player": 26, "surface": 20, "market": 19},
                        "model_prob": 0.55,
                        "fair_odds": 1.82,
                        "risk_score": 40,
                        "recommendation": "WATCH",
                        "ev_pct": 0,
                        "edge_pct": 0,
                        "favorite": "A",
                    }
                    summary = validate_tis.run_validation(limit=5, write_report=False)
        self.assertEqual(summary["n_evaluated"], 5)
        self.assertIn("tier_distribution", summary)

    def test_run_validation_empty_pairs(self):
        with patch.object(validate_tis, "_sample_pairs", return_value=[]):
            summary = validate_tis.run_validation(limit=10, write_report=False)
        self.assertIn("error", summary)
        self.assertEqual(summary["n"], 0)


class TestRenderMarkdown(unittest.TestCase):
    def test_render_includes_stats(self):
        md = validate_tis.render_markdown({
            "n_evaluated": 100,
            "n_requested": 200,
            "n_issues": 0,
            "tis_min": 40,
            "tis_max": 90,
            "tis_median": 65,
            "tis_mean": 64.5,
            "tier_distribution": {"WATCH": 50, "NO_BET": 50},
            "sample_issues": [],
            "sample_rows": [],
        })
        self.assertIn("100", md)
        self.assertIn("WATCH", md)


if __name__ == "__main__":
    unittest.main()
