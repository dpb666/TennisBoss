"""Tests pour deployment_history (bot/db.py) — journal des déploiements prod.

Contexte : scripts/deploy.sh enregistre chaque déploiement/rollback via
`run.py record-deploy` pour éliminer la dérive prod vs repo (risque R-6,
docs/ARCHITECTURE_BLUEPRINT.md §9.3).
"""
from __future__ import annotations

import os
import tempfile
import unittest

from bot import config, db


class TestDeploymentHistory(unittest.TestCase):
    def setUp(self):
        self._fd, self._path = tempfile.mkstemp(suffix=".db")
        self._save_db = config.DB_FILE
        config.DB_FILE = self._path
        db.init()

    def tearDown(self):
        config.DB_FILE = self._save_db
        os.close(self._fd)
        try:
            os.remove(self._path)
        except OSError:
            pass  # verrou Windows résiduel — le fichier temp sera nettoyé par l'OS

    def test_record_returns_id_and_is_listed(self):
        dep_id = db.record_deployment("abc1234", component="bot",
                                      result="success", notes="test deploy")
        self.assertGreater(dep_id, 0)
        rows = db.list_deployments()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["git_hash"], "abc1234")
        self.assertEqual(rows[0]["component"], "bot")
        self.assertEqual(rows[0]["result"], "success")
        self.assertEqual(rows[0]["notes"], "test deploy")
        self.assertTrue(rows[0]["deployed_at"])  # ISO timestamp non vide

    def test_list_orders_most_recent_first_and_respects_limit(self):
        for i in range(5):
            db.record_deployment(f"hash{i}")
        rows = db.list_deployments(limit=3)
        self.assertEqual(len(rows), 3)
        self.assertEqual([r["git_hash"] for r in rows], ["hash4", "hash3", "hash2"])

    def test_rollback_result_is_recorded(self):
        db.record_deployment("bad4567", result="rollback",
                             notes="rollback auto depuis fff0000 (health KO)")
        rows = db.list_deployments(limit=1)
        self.assertEqual(rows[0]["result"], "rollback")

    def test_schema_is_additive_and_reinit_safe(self):
        # init() rejoué (CREATE TABLE IF NOT EXISTS) ne perd pas les lignes.
        db.record_deployment("keep123")
        db.init()
        self.assertEqual(db.list_deployments()[0]["git_hash"], "keep123")


if __name__ == "__main__":
    unittest.main()
