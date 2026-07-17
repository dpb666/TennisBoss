"""Tests pour bot/live_api.py::load_env — isolation des clés d'auth.

Contexte (bug corrigé 2026-07-16) : load_env() injectait TOUT le .env dans
os.environ en effet de bord de n'importe quel fetch_* live_api — y compris
TENNISBOSS_API_TOKEN. Résultat : le premier test touchant live_api activait
l'auth pour tout le reste du process pytest (401 sur les tests API suivants).
Désormais les clés d'auth (_AUTH_KEYS) ne sont chargées que par les points
d'entrée serveur explicites (include_auth=True, api.serve).
"""
from __future__ import annotations

import os
import tempfile
import unittest

from bot import config, live_api


class TestLoadEnvAuthIsolation(unittest.TestCase):
    def setUp(self):
        self._dir = tempfile.mkdtemp()
        with open(os.path.join(self._dir, ".env"), "w", encoding="utf-8") as fh:
            fh.write("TENNISBOSS_API_TOKEN=secret-from-dotenv\n")
            fh.write("TENNISBOSS_ADMIN_TOKEN=admin-from-dotenv\n")
            fh.write("TB_TEST_PROVIDER_KEY=provider-value\n")
        self._save_root = config.ROOT
        config.ROOT = self._dir
        # Sauvegarde puis retire les clés de l'environnement réel du process.
        self._saved_env = {}
        for key in ("TENNISBOSS_API_TOKEN", "TENNISBOSS_ADMIN_TOKEN",
                    "TB_TEST_PROVIDER_KEY"):
            self._saved_env[key] = os.environ.pop(key, None)

    def tearDown(self):
        config.ROOT = self._save_root
        for key, val in self._saved_env.items():
            if val is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = val
        os.remove(os.path.join(self._dir, ".env"))
        os.rmdir(self._dir)

    def test_default_load_env_skips_auth_keys(self):
        live_api.load_env()
        self.assertEqual(os.environ.get("TB_TEST_PROVIDER_KEY"), "provider-value")
        self.assertIsNone(os.environ.get("TENNISBOSS_API_TOKEN"))
        self.assertIsNone(os.environ.get("TENNISBOSS_ADMIN_TOKEN"))
        os.environ.pop("TB_TEST_PROVIDER_KEY", None)

    def test_include_auth_loads_everything(self):
        live_api.load_env(include_auth=True)
        self.assertEqual(os.environ.get("TENNISBOSS_API_TOKEN"), "secret-from-dotenv")
        self.assertEqual(os.environ.get("TENNISBOSS_ADMIN_TOKEN"), "admin-from-dotenv")
        self.assertEqual(os.environ.get("TB_TEST_PROVIDER_KEY"), "provider-value")
        for key in ("TENNISBOSS_API_TOKEN", "TENNISBOSS_ADMIN_TOKEN",
                    "TB_TEST_PROVIDER_KEY"):
            os.environ.pop(key, None)

    def test_existing_env_value_is_never_overridden(self):
        os.environ["TB_TEST_PROVIDER_KEY"] = "from-shell"
        live_api.load_env(include_auth=True)
        self.assertEqual(os.environ.get("TB_TEST_PROVIDER_KEY"), "from-shell")
        for key in ("TENNISBOSS_API_TOKEN", "TENNISBOSS_ADMIN_TOKEN",
                    "TB_TEST_PROVIDER_KEY"):
            os.environ.pop(key, None)


if __name__ == "__main__":
    unittest.main()
