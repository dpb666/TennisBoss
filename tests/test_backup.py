"""Tests pour bot/backup.py — sauvegarde périodique de state/tennisboss.db.

Contexte : un incident réel (DB réinitialisée pendant une manipulation
manuelle de state/ alors que le service tournait) n'a été récupérable que
par chance. Ce module élimine ce hasard ; ces tests vérifient qu'il
fonctionne sur une DB réelle (temporaire), pas juste sur des mocks.
"""
from __future__ import annotations

import os
import sqlite3
import tempfile
import unittest
from unittest import mock

from bot import backup, config, db


class TestBackup(unittest.TestCase):
    def setUp(self):
        self._fd, self._path = tempfile.mkstemp(suffix=".db")
        self._save_db = config.DB_FILE
        config.DB_FILE = self._path
        db.init()

        self._backup_dir_fd = tempfile.mkdtemp()
        self._save_backup_dir = backup.BACKUP_DIR
        backup.BACKUP_DIR = self._backup_dir_fd

    def tearDown(self):
        config.DB_FILE = self._save_db
        os.close(self._fd)
        if os.path.exists(self._path):
            os.remove(self._path)
        backup.BACKUP_DIR = self._save_backup_dir

    def test_backup_now_creates_a_consistent_copy(self):
        db.insert_settled({
            "event_key": "e1", "date": "2026-07-01", "tour": "atp",
            "player1": "A", "player2": "B", "winner": "A",
        })
        path = backup.backup_now()
        self.assertIsNotNone(path)
        self.assertTrue(os.path.exists(path))

        copy = sqlite3.connect(path)
        n = copy.execute("SELECT COUNT(*) FROM settled_matches").fetchone()[0]
        self.assertEqual(n, 1)
        copy.close()

    def test_list_backups_returns_created_files(self):
        backup.backup_now()
        backup.backup_now()
        self.assertEqual(len(backup.list_backups()), 2)

    def test_prune_keeps_only_max_backups(self):
        for _ in range(5):
            backup.backup_now()
        self.assertEqual(len(backup.list_backups()), 5)
        with mock.patch.object(backup, "MAX_BACKUPS", 3):
            backup.backup_now()  # 6e backup -> prune à 3
        self.assertEqual(len(backup.list_backups()), 3)

    def test_backup_now_returns_none_without_source_db(self):
        os.remove(config.DB_FILE)
        self.assertIsNone(backup.backup_now())


if __name__ == "__main__":
    import unittest.mock  # noqa: E402
    unittest.main()
