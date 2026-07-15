"""Unit tests for bot.surface_features."""
from __future__ import annotations

import unittest

from bot.surface_features import (
    MatchHistoryIndex,
    fatigue_on_surface,
    fit_surface_weights,
    surface_elo_diff,
    surface_feature_diffs,
    surface_logit_from_diffs,
    surface_momentum,
    tournament_surface_experience,
    weighted_recent_form_surface,
    win_rate_surface,
)


def _match(w: str, l: str, date: str, surface: str, mid: int = 0) -> dict:
    return {
        "id": mid,
        "winner_name": w,
        "loser_name": l,
        "date": date,
        "surface": surface,
    }


class TestMatchHistoryIndex(unittest.TestCase):
    def test_filters_by_surface_and_date(self):
        rows = [
            _match("A", "B", "20260101", "clay", 1),
            _match("A", "C", "20260110", "hard", 2),
            _match("A", "D", "20260120", "clay", 3),
        ]
        idx = MatchHistoryIndex(rows)
        clay = idx.player_matches("A", before_date="20260125", surface="clay")
        self.assertEqual(len(clay), 2)
        self.assertTrue(all(r["surface"] == "clay" for r in clay))

    def test_add_match_extends_index(self):
        idx = MatchHistoryIndex([_match("A", "B", "20260101", "hard", 1)])
        idx.add_match(_match("A", "C", "20260115", "clay", 2))
        self.assertEqual(len(idx.player_matches("A")), 2)


class TestWinRateSurface(unittest.TestCase):
    def test_win_rate_on_clay(self):
        rows = [
            _match("A", "B", "20260101", "clay", 1),
            _match("C", "A", "20260110", "clay", 2),
            _match("A", "D", "20260120", "clay", 3),
        ]
        idx = MatchHistoryIndex(rows)
        wr = win_rate_surface("A", "clay", idx, "20260201", n=10)
        self.assertAlmostEqual(wr, 2 / 3, places=4)

    def test_none_without_surface_history(self):
        idx = MatchHistoryIndex([_match("A", "B", "20260101", "hard", 1)])
        self.assertIsNone(win_rate_surface("A", "clay", idx, "20260201"))


class TestWeightedFormSurface(unittest.TestCase):
    def test_ema_between_zero_and_one(self):
        rows = [
            _match("A", "B", "20260101", "hard", 1),
            _match("C", "A", "20260110", "hard", 2),
        ]
        idx = MatchHistoryIndex(rows)
        form = weighted_recent_form_surface("A", "hard", idx, "20260201")
        self.assertIsNotNone(form)
        self.assertGreaterEqual(form, 0.0)
        self.assertLessEqual(form, 1.0)


class TestSurfaceEloDiff(unittest.TestCase):
    def test_normalised_diff(self):
        elo_surf = {"hard": {"A": 1600.0, "B": 1400.0}}
        diff = surface_elo_diff("A", "B", "hard", elo_surf)
        self.assertAlmostEqual(diff, 0.5, places=4)


class TestSurfaceMomentum(unittest.TestCase):
    def test_positive_when_recent_better(self):
        rows = [
            _match("C", "A", "20260101", "clay", 1),
            _match("D", "A", "20260105", "clay", 2),
            _match("A", "E", "20260120", "clay", 3),
            _match("A", "F", "20260125", "clay", 4),
        ]
        idx = MatchHistoryIndex(rows)
        mom = surface_momentum("A", "clay", idx, "20260201", recent_n=2, baseline_n=4)
        self.assertIsNotNone(mom)
        self.assertGreater(mom, 0.0)


class TestFatigueOnSurface(unittest.TestCase):
    def test_days_since_last_surface_match(self):
        rows = [_match("A", "B", "20260101", "grass", 1)]
        idx = MatchHistoryIndex(rows)
        fatigue = fatigue_on_surface("A", "grass", idx, "20260115")
        self.assertEqual(fatigue, 14.0)


class TestTournamentSurfaceExperience(unittest.TestCase):
    def test_counts_surface_matches(self):
        rows = [
            _match("A", "B", "20260101", "clay", 1),
            _match("A", "C", "20260110", "clay", 2),
            _match("A", "D", "20260120", "hard", 3),
        ]
        idx = MatchHistoryIndex(rows)
        self.assertEqual(tournament_surface_experience("A", "clay", idx, "20260201"), 2)


class TestSurfaceFeatureDiffs(unittest.TestCase):
    def test_returns_all_diff_keys(self):
        rows = [
            _match("A", "B", "20260101", "hard", 1),
            _match("B", "A", "20260110", "hard", 2),
        ]
        idx = MatchHistoryIndex(rows)
        diffs = surface_feature_diffs("A", "B", "hard", idx, "20260201")
        self.assertIn("win_rate_surface_diff", diffs)
        self.assertIn("surface_momentum_diff", diffs)


class TestFitSurfaceWeights(unittest.TestCase):
    def test_learns_positive_weight_for_predictive_feature(self):
        train = []
        for i in range(40):
            diffs = {"win_rate_surface_diff": 0.2 if i % 2 == 0 else -0.2}
            for name in (
                "win_rate_surface_20_diff",
                "weighted_form_surface_diff",
                "surface_momentum_diff",
                "fatigue_on_surface_diff",
                "tournament_surface_exp_diff",
            ):
                diffs[name] = 0.0
            y = 1.0 if i % 2 == 0 else 0.0
            train.append((diffs, y))
        weights = fit_surface_weights(
            train,
            ("win_rate_surface_diff", "win_rate_surface_20_diff",
             "weighted_form_surface_diff", "surface_momentum_diff",
             "fatigue_on_surface_diff", "tournament_surface_exp_diff"),
            iters=600,
        )
        self.assertGreater(weights["win_rate_surface_diff"], 0.0)

    def test_surface_logit_combines_weights(self):
        diffs = {"win_rate_surface_diff": 0.1}
        z = surface_logit_from_diffs(diffs, {"win_rate_surface_diff": 2.0})
        self.assertAlmostEqual(z, 0.2, places=4)


if __name__ == "__main__":
    unittest.main()
