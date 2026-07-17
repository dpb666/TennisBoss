"""Tests pour bot/backup.py::prune_state_tmp — janitor de state/.

Contexte : 86 fichiers tmp*.json.corrupt de 0 octet accumulés en production
(restes d'écritures atomiques interrompues, 2026-07-12 → 16). Le janitor les
purge après JANITOR_MAX_AGE_DAYS jours, sans jamais toucher memory.json.corrupt
(artefact de self-healing volontairement conservé).
Voir docs/ARCHITECTURE_BLUEPRINT.md, dette D-7.
"""
from __future__ import annotations

import os
import tempfile
import time
import unittest

from bot import backup, config


def _touch(path: str, age_days: float) -> None:
    with open(path, "w", encoding="utf-8"):
        pass
    old = time.time() - age_days * 86400
    os.utime(path, (old, old))


class TestStateJanitor(unittest.TestCase):
    def setUp(self):
        self._dir = tempfile.mkdtemp()
        self._save_state_dir = config.STATE_DIR
        config.STATE_DIR = self._dir

    def tearDown(self):
        config.STATE_DIR = self._save_state_dir
        for name in os.listdir(self._dir):
            os.remove(os.path.join(self._dir, name))
        os.rmdir(self._dir)

    def test_old_corrupt_tmp_files_are_removed(self):
        _touch(os.path.join(self._dir, "tmpabc123.json.corrupt"), age_days=8)
        _touch(os.path.join(self._dir, "tmpxyz789.tmp"), age_days=30)
        removed = backup.prune_state_tmp()
        self.assertEqual(removed, 2)
        self.assertEqual(
            [n for n in os.listdir(self._dir) if n.startswith("tmp")], [])

    def test_recent_files_are_kept(self):
        _touch(os.path.join(self._dir, "tmpfresh.json.corrupt"), age_days=1)
        removed = backup.prune_state_tmp()
        self.assertEqual(removed, 0)
        self.assertTrue(os.path.exists(os.path.join(self._dir, "tmpfresh.json.corrupt")))

    def test_memory_json_corrupt_is_never_touched(self):
        # Artefact de self-healing (bot/memory.py::_backup_corrupt) : diagnostic
        # potentiellement utile, ne matche pas les motifs tmp* du janitor.
        _touch(os.path.join(self._dir, "memory.json.corrupt"), age_days=60)
        removed = backup.prune_state_tmp()
        self.assertEqual(removed, 0)
        self.assertTrue(os.path.exists(os.path.join(self._dir, "memory.json.corrupt")))

    def test_regular_state_files_are_never_touched(self):
        _touch(os.path.join(self._dir, "memory.json"), age_days=60)
        _touch(os.path.join(self._dir, "config.json"), age_days=60)
        removed = backup.prune_state_tmp()
        self.assertEqual(removed, 0)
        self.assertEqual(len(os.listdir(self._dir)), 2)

    def test_explicit_max_age_overrides_default(self):
        _touch(os.path.join(self._dir, "tmpmidage.json.corrupt"), age_days=3)
        self.assertEqual(backup.prune_state_tmp(), 0)          # défaut 7j : gardé
        self.assertEqual(backup.prune_state_tmp(max_age_days=2), 1)  # 2j : purgé


if __name__ == "__main__":
    unittest.main()
