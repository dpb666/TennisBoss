"""Tests CLV closing backfill (last_seen → snapshot)."""
import os
import tempfile
import unittest

from bot import clv, clv_backfill, config, db


class TestCLVBackfill(unittest.TestCase):
    def setUp(self):
        self._fd, self._path = tempfile.mkstemp(suffix=".db")
        self._save = config.DB_FILE
        config.DB_FILE = self._path
        db.init()

    def tearDown(self):
        config.DB_FILE = self._save
        os.close(self._fd)
        os.remove(self._path)

    def test_backfill_from_market_snapshot(self):
        clv.seed_pick("ev1", "2026-07-16", "A", "B", "A", 2.00, 0.55, 0.6)
        clv.settle("A", "B", "A")
        self.assertEqual(db.list_clv()[0]["closing_src"], "last_seen")

        db.record_market_snapshot("ev1", "A", "B", 1.70, 2.40, hours_ahead=0.5)
        result = clv_backfill.backfill_last_seen_closing(
            since="2026-07-15", use_odds_api=False,
        )
        self.assertEqual(result["fixed"], 1)
        self.assertEqual(result["fixed_from_snapshot"], 1)
        row = db.list_clv()[0]
        self.assertEqual(row["closing_src"], "snapshot_backfill")
        self.assertAlmostEqual(row["closing_odds"], 1.70)
        self.assertAlmostEqual(row["clv_pct"], round((2.0 / 1.7 - 1) * 100, 2))

    def test_dry_run_does_not_write(self):
        clv.seed_pick("ev2", "2026-07-16", "C", "D", "D", 3.00, 0.40, 0.55)
        clv.settle("C", "D", "C")
        db.record_market_snapshot("ev2", "C", "D", 1.50, 2.80, hours_ahead=0.2)
        result = clv_backfill.backfill_last_seen_closing(
            since="2026-07-15", dry_run=True, use_odds_api=False,
        )
        self.assertEqual(result["fixed"], 1)
        self.assertEqual(db.list_clv()[0]["closing_src"], "last_seen")

    def test_skips_when_no_snapshot(self):
        clv.seed_pick("ev3", "2026-07-16", "E", "F", "E", 2.10, 0.52, 0.55)
        clv.settle("E", "F", "F")
        result = clv_backfill.backfill_last_seen_closing(
            since="2026-07-15", use_odds_api=False,
        )
        self.assertEqual(result["fixed"], 0)
        self.assertEqual(result["skipped_no_source"], 1)


if __name__ == "__main__":
    unittest.main()
