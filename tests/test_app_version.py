"""Tests pour le bandeau "mise à jour disponible" (bot/db.py::set_app_version/
get_app_version_info, GET /api/app/version) — avant publication Play Store,
qui gérera cela nativement. Voir docs/AI_ASSISTANT_ARCHITECTURE.md pour le
contexte (fonctionnalité produit, pas liée à l'assistant IA).
"""
from __future__ import annotations

import os
import tempfile
import unittest

from bot import api, config, db


class AppVersionTestCase(unittest.TestCase):
    def setUp(self):
        self._fd, self._path = tempfile.mkstemp(suffix=".db")
        self._save = config.DB_FILE
        config.DB_FILE = self._path
        db.init()

    def tearDown(self):
        config.DB_FILE = self._save
        os.close(self._fd)
        os.remove(self._path)


class TestSetAndGetAppVersion(AppVersionTestCase):
    def test_no_version_published_returns_none(self):
        self.assertIsNone(db.get_app_version_info())

    def test_set_then_get_roundtrip(self):
        db.set_app_version(3, "1.2", notes="Bet builder + combos",
                           download_url="https://example.com/app.apk")
        info = db.get_app_version_info()
        self.assertEqual(info["version_code"], 3)
        self.assertEqual(info["version_name"], "1.2")
        self.assertEqual(info["notes"], "Bet builder + combos")
        self.assertEqual(info["download_url"], "https://example.com/app.apk")
        self.assertIn("published_ts", info)

    def test_set_without_optional_fields(self):
        db.set_app_version(2, "1.1")
        info = db.get_app_version_info()
        self.assertEqual(info["notes"], "")
        self.assertIsNone(info["download_url"])

    def test_set_overwrites_previous(self):
        db.set_app_version(2, "1.1")
        db.set_app_version(3, "1.2")
        info = db.get_app_version_info()
        self.assertEqual(info["version_code"], 3)


class TestApiAppVersion(AppVersionTestCase):
    def setUp(self):
        super().setUp()
        api.app.testing = True
        self.client = api.app.test_client()

    def test_no_version_published(self):
        resp = self.client.get("/api/app/version")
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(resp.get_json()["available"])

    def test_version_published(self):
        db.set_app_version(3, "1.2", notes="Nouveautés")
        resp = self.client.get("/api/app/version")
        data = resp.get_json()
        self.assertTrue(data["available"])
        self.assertEqual(data["version_code"], 3)
        self.assertEqual(data["version_name"], "1.2")
        self.assertEqual(data["notes"], "Nouveautés")


if __name__ == "__main__":
    unittest.main()
