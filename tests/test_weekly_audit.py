"""Tests for bot/weekly_audit.py and run.py weekly-audit CLI."""
from __future__ import annotations

import json
import os
import sqlite3
import tempfile
import unittest
from io import StringIO
from unittest import mock

from bot import config, db, weekly_audit


class TestWeeklyAudit(unittest.TestCase):
    def setUp(self):
        fd, self._path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        self._save_db = config.DB_FILE
        config.DB_FILE = self._path
        db.init()
        db.log_clv_pick(
            "ek1", "2026-07-17", "A", "B", "A", 2.0, 0.55, 0.7,
            repro={
                "tournament": "Test Open", "tournament_level": "atp250",
                "surface": "hard", "player_rank": 10, "opponent_rank": 20,
                "ranking_diff": -10, "model_prob_raw": 0.5,
                "model_prob_calibrated": 0.52, "market_prob": 0.48,
                "market_disagreement": 0.04, "ev_pct": 8.0, "calib_k": 1.0,
                "market_blend_w": 0.3, "calibration_version": "v1",
                "predictor_version": "v1", "feature_set_version": "v1",
            },
        )

    def tearDown(self):
        config.DB_FILE = self._save_db
        for path in (self._path, self._path + "-wal", self._path + "-shm"):
            try:
                if os.path.exists(path):
                    os.remove(path)
            except OSError:
                pass

    def test_run_audit_returns_expected_keys(self):
        audit = weekly_audit.run_audit(days=7, logging_hours=24)
        self.assertIn("bet_history", audit)
        self.assertIn("logging_recent", audit)
        self.assertIn("clv", audit)
        self.assertIn("pick_volume", audit)
        self.assertIn("calendar_note", audit)
        self.assertEqual(audit["pick_volume"]["clv_seeded"], 1)

    def test_format_report_includes_calendar_note(self):
        audit = weekly_audit.run_audit(days=7)
        text = weekly_audit.format_report(audit)
        self.assertIn("Note calendrier", text)
        self.assertIn("Ne pas élargir", text)

    def test_clv_logging_completeness_recent(self):
        report = db.clv_logging_completeness_recent(hours=24)
        self.assertEqual(report["n"], 1)
        self.assertEqual(report["completeness_pct"], 100.0)

    def test_cmd_weekly_audit_prints_report(self):
        from run import cmd_weekly_audit

        args = mock.Mock(days=7, logging_hours=24, json=False, telegram=False)
        buf = StringIO()
        with mock.patch("sys.stdout", buf):
            cmd_weekly_audit(args)
        out = buf.getvalue()
        self.assertIn("Weekly audit", out)
        self.assertIn("Note calendrier", out)

    def test_cmd_weekly_audit_json_flag(self):
        from run import cmd_weekly_audit

        args = mock.Mock(days=7, logging_hours=24, json=True, telegram=False)
        buf = StringIO()
        with mock.patch("sys.stdout", buf):
            cmd_weekly_audit(args)
        self.assertIn("--- JSON ---", buf.getvalue())
        payload = buf.getvalue().split("--- JSON ---", 1)[1].strip()
        data = json.loads(payload)
        self.assertIn("summary", data)


if __name__ == "__main__":
    unittest.main()
