"""Tests pour bot/scheduler.py::job_daily_digest — le garde-fou anti-doublon
est le point critique : un redémarrage du service dans la même journée ne
doit jamais renvoyer un 2e digest (schedule.every().day.at(...) seul ne
suffit pas à garantir ça après un restart)."""
from __future__ import annotations

import os
import tempfile
import unittest
from unittest.mock import patch

from bot import config, db, scheduler as sched_mod


class TestJobDailyDigest(unittest.TestCase):
    def setUp(self):
        self._fd, self._path = tempfile.mkstemp(suffix=".db")
        self._save = config.DB_FILE
        config.DB_FILE = self._path
        db.init()
        self.scheduler = sched_mod.TennisBossScheduler()

    def tearDown(self):
        config.DB_FILE = self._save
        os.close(self._fd)
        os.remove(self._path)

    def test_sends_digest_and_records_date(self):
        fake_digest = {"title": "🎾 Ton résumé", "body": "1W-0L", "cold_start": False}
        with patch("bot.scheduler.recommendations.daily_digest", return_value=fake_digest), \
             patch("bot.scheduler.push_notifications.broadcast", return_value=2) as mocked_broadcast:
            self.scheduler.job_daily_digest()

        mocked_broadcast.assert_called_once_with("🎾 Ton résumé", "1W-0L")
        self.assertEqual(self.scheduler.jobs_run, 1)

    def test_does_not_send_twice_the_same_day(self):
        fake_digest = {"title": "T", "body": "B", "cold_start": False}
        with patch("bot.scheduler.recommendations.daily_digest", return_value=fake_digest), \
             patch("bot.scheduler.push_notifications.broadcast", return_value=1) as mocked_broadcast:
            self.scheduler.job_daily_digest()
            self.scheduler.job_daily_digest()  # simule un 2e appel le même jour

        mocked_broadcast.assert_called_once()

    def test_failure_does_not_mark_digest_as_sent(self):
        with patch("bot.scheduler.recommendations.daily_digest", side_effect=RuntimeError("boom")), \
             patch("bot.scheduler.push_notifications.broadcast") as mocked_broadcast:
            self.scheduler.job_daily_digest()
        mocked_broadcast.assert_not_called()
        self.assertIsNone(db.get_meta("last_daily_digest_date"))


class TestJobMtdIngest(unittest.TestCase):
    """job_mtd_ingest : voir bot/mantennisdata_feeder.py (remplacement de
    Sackmann pour l'ingestion continue ATP)."""

    def setUp(self):
        self.scheduler = sched_mod.TennisBossScheduler()

    def test_calls_feeder_and_increments_jobs_run(self):
        with patch("bot.scheduler.mantennisdata_feeder.ingest",
                   return_value={"trained": 3, "inserted": 3}) as mocked:
            self.scheduler.job_mtd_ingest()
        mocked.assert_called_once_with()
        self.assertEqual(self.scheduler.jobs_run, 1)

    def test_failure_is_caught_and_does_not_raise(self):
        with patch("bot.scheduler.mantennisdata_feeder.ingest",
                   side_effect=RuntimeError("boom")):
            self.scheduler.job_mtd_ingest()  # ne doit pas lever
        self.assertEqual(self.scheduler.jobs_run, 0)


class TestJobRankings(unittest.TestCase):
    def setUp(self):
        self._fd, self._path = tempfile.mkstemp(suffix=".db")
        self._save = config.DB_FILE
        config.DB_FILE = self._path
        db.init()
        self.scheduler = sched_mod.TennisBossScheduler()

    def tearDown(self):
        config.DB_FILE = self._save
        os.close(self._fd)
        os.remove(self._path)

    def test_rankings_runs_once_per_iso_week(self):
        fake = {"live_rankings_upserted": 10, "memory_synced": 5,
                "coverage": {"official_pct_active": 70.0}}
        with patch("bot.scheduler.ranking_feeder.ingest", return_value=fake) as mocked:
            self.scheduler.job_rankings()
            self.scheduler.job_rankings()
        mocked.assert_called_once()
        self.assertEqual(self.scheduler.jobs_run, 1)

    def test_rankings_failure_does_not_mark_week(self):
        with patch("bot.scheduler.ranking_feeder.ingest", side_effect=RuntimeError("net")):
            self.scheduler.job_rankings()
        self.assertIsNone(db.get_meta("last_rankings_ingest_week"))


class TestJobBetHistoryBackfill(unittest.TestCase):
    def setUp(self):
        self._fd, self._path = tempfile.mkstemp(suffix=".db")
        self._save = config.DB_FILE
        config.DB_FILE = self._path
        db.init()
        self.scheduler = sched_mod.TennisBossScheduler()

    def tearDown(self):
        config.DB_FILE = self._save
        os.close(self._fd)
        os.remove(self._path)

    def test_backfill_once_per_day(self):
        with patch("bot.scheduler.db.backfill_bet_history_from_clv",
                   return_value={"added": 3, "patched": 1}) as mocked:
            self.scheduler.job_bet_history_backfill()
            self.scheduler.job_bet_history_backfill()
        mocked.assert_called_once()
        self.assertEqual(self.scheduler.jobs_run, 1)


class TestJobMonitor(unittest.TestCase):
    def setUp(self):
        self._fd, self._path = tempfile.mkstemp(suffix=".db")
        self._save = config.DB_FILE
        config.DB_FILE = self._path
        db.init()
        self.scheduler = sched_mod.TennisBossScheduler()

    def tearDown(self):
        config.DB_FILE = self._save
        os.close(self._fd)
        os.remove(self._path)

    def test_monitor_persists_last_check(self):
        fake_result = {
            "timestamp": "2026-07-15T18:00:00",
            "checks": {"database": {"status": "ok"}},
            "alerts": ["bet_history sparse: 97 settled (need 200+ for calibration)"],
            "overall_status": "warning",
        }
        with patch("bot.scheduler.monitor.SystemMonitor") as MockMon:
            MockMon.return_value.run_full_check.return_value = fake_result
            self.scheduler.job_monitor()

        raw = db.get_meta("last_monitor_check")
        self.assertIsNotNone(raw)
        import json as _json
        persisted = _json.loads(raw)
        self.assertEqual(persisted["overall_status"], "warning")
        self.assertEqual(self.scheduler.jobs_run, 1)

    def test_monitor_failure_does_not_persist(self):
        with patch("bot.scheduler.monitor.SystemMonitor") as MockMon:
            MockMon.return_value.run_full_check.side_effect = RuntimeError("boom")
            self.scheduler.job_monitor()
        self.assertIsNone(db.get_meta("last_monitor_check"))


class TestJobCalibrationReport(unittest.TestCase):
    def setUp(self):
        self._fd, self._path = tempfile.mkstemp(suffix=".db")
        self._save = config.DB_FILE
        config.DB_FILE = self._path
        db.init()
        self.scheduler = sched_mod.TennisBossScheduler()

    def tearDown(self):
        config.DB_FILE = self._save
        os.close(self._fd)
        os.remove(self._path)

    def test_calibration_report_once_per_week(self):
        fake_report = {"n_settled": 94, "brier_score": 0.231, "verdict": "sparse"}
        with patch("bot.calibration_report.generate",
                   return_value=("reports/calibration_report.md", fake_report)):
            self.scheduler.job_calibration_report()
            self.scheduler.job_calibration_report()
        self.assertEqual(self.scheduler.jobs_run, 1)
        self.assertIsNotNone(db.get_meta("last_calibration_report_week"))


if __name__ == "__main__":
    unittest.main()
