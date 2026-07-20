"""Tests pour l'instrumentation de reproductibilité des picks (Data
Observability, 2026-07-15) : validation de complétude, rapport de santé,
niveau de tournoi, cote d'ouverture. Voir docs/LOGGING_SCHEMA.md.
"""
from __future__ import annotations

import os
import tempfile
import unittest

from bot import clv, config, db


class LoggingSchemaTestCase(unittest.TestCase):
    def setUp(self):
        self._fd, self._path = tempfile.mkstemp(suffix=".db")
        self._save = config.DB_FILE
        config.DB_FILE = self._path
        db.init()

    def tearDown(self):
        config.DB_FILE = self._save
        os.close(self._fd)
        os.remove(self._path)

    def _complete_repro(self, **overrides):
        repro = {
            "tournament": "ATP Miami", "tournament_level": "tour", "surface": "hard",
            "player_rank": 10.0, "opponent_rank": 20.0, "ranking_diff": 10.0,
            "model_prob_raw": 0.6, "model_prob_calibrated": 0.55, "market_prob": 0.52,
            "market_disagreement": 0.03, "ev_pct": 8.5, "calib_k": 0.21,
            "market_blend_w": 0.0, "calibration_version": "1.0",
            "predictor_version": "1.0", "feature_set_version": "1.0",
        }
        repro.update(overrides)
        return repro


class TestValidateClvPickRow(LoggingSchemaTestCase):
    def test_complete_row_has_no_missing_fields(self):
        clv.seed_pick("v1", "2026-07-15", "A", "B", "A", 2.0, 0.55, 0.6,
                      repro=self._complete_repro())
        row = db.list_clv()[0]
        self.assertEqual(db.validate_clv_pick_row(row), [])

    def test_missing_fields_are_detected(self):
        clv.seed_pick("v2", "2026-07-15", "C", "D", "C", 2.0, 0.55, 0.6)
        row = db.list_clv()[0]
        missing = db.validate_clv_pick_row(row)
        self.assertIn("tournament", missing)
        self.assertIn("ev_pct", missing)
        self.assertEqual(set(missing), set(db.CLV_REPRO_FIELDS))

    def test_opening_and_closing_odds_not_required(self):
        # opening_odds/closing_odds ne font pas partie de CLV_REPRO_FIELDS.
        self.assertNotIn("opening_odds", db.CLV_REPRO_FIELDS)
        self.assertNotIn("closing_odds", db.CLV_REPRO_FIELDS)


class TestFindIncompleteClvPicks(LoggingSchemaTestCase):
    def test_finds_only_incomplete_rows(self):
        clv.seed_pick("i1", "2026-07-15", "A", "B", "A", 2.0, 0.55, 0.6,
                      repro=self._complete_repro())
        clv.seed_pick("i2", "2026-07-15", "C", "D", "C", 2.0, 0.55, 0.6)
        incomplete = db.find_incomplete_clv_picks()
        keys = {p["event_key"] for p in incomplete}
        self.assertIn("i2", keys)
        self.assertNotIn("i1", keys)

    def test_empty_db_returns_empty_list(self):
        self.assertEqual(db.find_incomplete_clv_picks(), [])


class TestClvLoggingCompletenessReport(LoggingSchemaTestCase):
    def test_empty_db(self):
        report = db.clv_logging_completeness_report()
        self.assertEqual(report["n_total"], 0)
        self.assertIsNone(report["completeness_pct_overall"])

    def test_mixed_completeness_reported_correctly(self):
        clv.seed_pick("c1", "2026-07-01", "A", "B", "A", 2.0, 0.55, 0.6,
                      repro=self._complete_repro())
        clv.seed_pick("c2", "2026-07-01", "C", "D", "C", 2.0, 0.55, 0.6,
                      repro=self._complete_repro())
        clv.seed_pick("c3", "2026-07-01", "E", "F", "E", 2.0, 0.55, 0.6)
        report = db.clv_logging_completeness_report()
        self.assertEqual(report["n_total"], 3)
        self.assertEqual(report["n_complete"], 2)
        self.assertAlmostEqual(report["completeness_pct_overall"], 66.7, places=1)
        self.assertEqual(report["missing_field_counts"]["tournament"], 1)

    def test_by_period_buckets_sum_to_total(self):
        clv.seed_pick("p1", "2026-01-01", "A", "B", "A", 2.0, 0.55, 0.6,
                      repro=self._complete_repro())
        clv.seed_pick("p2", "2026-02-15", "C", "D", "C", 2.0, 0.55, 0.6)
        report = db.clv_logging_completeness_report(bucket="week")
        total_bucketed = sum(v["n"] for v in report["by_period"].values())
        self.assertEqual(total_bucketed, 2)


class TestTournamentLevelFromName(unittest.TestCase):
    def test_grand_slam(self):
        self.assertEqual(config.tournament_level_from_name("Wimbledon"), "grand_slam")
        self.assertEqual(config.tournament_level_from_name("US Open"), "grand_slam")

    def test_challenger_itf(self):
        self.assertEqual(config.tournament_level_from_name("Challenger Prague"), "challenger_itf")
        self.assertEqual(config.tournament_level_from_name("ITF W25 Sharm"), "challenger_itf")

    def test_tour(self):
        self.assertEqual(config.tournament_level_from_name("ATP Miami"), "tour")
        self.assertEqual(config.tournament_level_from_name("WTA Rome"), "tour")

    def test_other_and_empty(self):
        self.assertEqual(config.tournament_level_from_name("Exhibition Team Cup"), "other")
        self.assertEqual(config.tournament_level_from_name(""), "other")
        self.assertEqual(config.tournament_level_from_name(None), "other")


class TestEarliestMarketSnapshot(LoggingSchemaTestCase):
    def test_no_snapshot_returns_none(self):
        self.assertIsNone(db.earliest_market_snapshot("nope"))

    def test_returns_first_by_timestamp(self):
        db.record_market_snapshot("ev1", "A", "B", 2.5, 1.6, hours_ahead=10.0)
        db.record_market_snapshot("ev1", "A", "B", 2.2, 1.75, hours_ahead=2.0)
        snap = db.earliest_market_snapshot("ev1")
        self.assertEqual(snap["odds_home"], 2.5)


class TestRankingAwareValidation(LoggingSchemaTestCase):
    def test_unranked_opponent_not_counted_missing(self):
        repro = self._complete_repro(
            player_rank=50.0, opponent_rank=None, ranking_diff=None,
        )
        clv.seed_pick("rk1", "2026-07-16", "A", "B", "A", 2.0, 0.55, 0.6, repro=repro)
        row = db.list_clv()[0]
        rankings = {"A": 50}
        self.assertEqual(db.validate_clv_pick_row(row, rankings=rankings), [])

    def test_lookup_player_rank_name_variants(self):
        rankings = {"Gentzsch, Tom": 212}
        self.assertEqual(db.lookup_player_rank("Tom Gentzsch", rankings), 212)


class TestResolvePickSurface(LoggingSchemaTestCase):
    def test_league_city_dict(self):
        surf = db.resolve_pick_surface(
            "A", "B", "Challenger - Pozoblanco, Spain",
        )
        self.assertEqual(surf, "clay")

    def test_value_pick_fallback(self):
        db.log_value_pick("2026-07-16", "A", "B", "A", 2.0, 10.0, surface="grass")
        surf = db.resolve_pick_surface("A", "B", "Unknown Event")
        self.assertEqual(surf, "grass")


class TestCompletenessSinceFilter(LoggingSchemaTestCase):
    def test_since_excludes_legacy_rows(self):
        clv.seed_pick("old1", "2026-06-01", "A", "B", "A", 2.0, 0.55, 0.6)
        clv.seed_pick("new1", "2026-07-16", "C", "D", "C", 2.0, 0.55, 0.6,
                      repro=self._complete_repro())
        report = db.clv_logging_completeness_report(since=db.CLV_REPRO_EPOCH)
        self.assertEqual(report["n_total"], 1)
        self.assertEqual(report["n_complete"], 1)
        self.assertEqual(report["completeness_pct_overall"], 100.0)


class TestBackfillClvRepro(LoggingSchemaTestCase):
    def test_backfills_surface_from_league(self):
        clv.seed_pick(
            "bf1", "2026-07-16", "A", "B", "A", 2.0, 0.55, 0.6,
            repro=self._complete_repro(surface=None, tournament="Challenger - Winnipeg, Canada"),
        )
        result = db.backfill_clv_repro_fields(since=db.CLV_REPRO_EPOCH)
        self.assertGreaterEqual(result["patched_rows"], 1)
        row = db.list_clv()[0]
        self.assertEqual(row["surface"], "hard")


if __name__ == "__main__":
    unittest.main()
