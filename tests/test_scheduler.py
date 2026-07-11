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


if __name__ == "__main__":
    unittest.main()
