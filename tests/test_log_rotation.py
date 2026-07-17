"""Tests pour bot/log.py — rotation par taille du fichier de log.

Contexte : logs/tennisboss.log croissait sans limite (dette D-18,
docs/ARCHITECTURE_BLUEPRINT.md). Rotation : tennisboss.log -> .1 -> .2 -> .3.
"""
from __future__ import annotations

import os
import tempfile
import unittest

from bot import config
from bot import log as log_mod


class TestLogRotation(unittest.TestCase):
    def setUp(self):
        self._dir = tempfile.mkdtemp()
        self._save_logs_dir = config.LOGS_DIR
        self._save_log_file = config.LOG_FILE
        self._save_max = log_mod._MAX_BYTES
        self._save_fh = log_mod._fh
        config.LOGS_DIR = self._dir
        config.LOG_FILE = os.path.join(self._dir, "test.log")
        log_mod._fh = None

    def tearDown(self):
        if log_mod._fh is not None:
            try:
                log_mod._fh.close()
            except OSError:
                pass
        log_mod._fh = self._save_fh
        log_mod._MAX_BYTES = self._save_max
        config.LOGS_DIR = self._save_logs_dir
        config.LOG_FILE = self._save_log_file
        for name in os.listdir(self._dir):
            os.remove(os.path.join(self._dir, name))
        os.rmdir(self._dir)

    def test_no_rotation_below_threshold(self):
        log_mod._MAX_BYTES = 10_000
        log_mod.log("petite ligne")
        self.assertTrue(os.path.exists(config.LOG_FILE))
        self.assertFalse(os.path.exists(config.LOG_FILE + ".1"))

    def test_rotation_over_threshold(self):
        log_mod._MAX_BYTES = 200
        for i in range(10):
            log_mod.log(f"ligne de remplissage numero {i} " + "x" * 40)
        self.assertTrue(os.path.exists(config.LOG_FILE + ".1"))
        # Le fichier courant a été réouvert et reste sous le seuil + une ligne.
        self.assertLess(os.path.getsize(config.LOG_FILE), 400)

    def test_rotated_files_shift_and_oldest_is_capped(self):
        log_mod._MAX_BYTES = 120
        for i in range(60):
            log_mod.log(f"rotation {i} " + "y" * 60)
        # .1 à .3 existent, pas de .4 (KEEP=3 par défaut).
        self.assertTrue(os.path.exists(config.LOG_FILE + ".1"))
        self.assertTrue(os.path.exists(config.LOG_FILE + ".3"))
        self.assertFalse(os.path.exists(config.LOG_FILE + ".4"))

    def test_logging_continues_after_rotation(self):
        log_mod._MAX_BYTES = 150
        for i in range(8):
            log_mod.log("avant rotation " + "z" * 50)
        log_mod.log("message apres rotation")
        with open(config.LOG_FILE, encoding="utf-8") as fh:
            content = fh.read()
        self.assertIn("message apres rotation", content)


if __name__ == "__main__":
    unittest.main()
