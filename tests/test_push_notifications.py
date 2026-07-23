"""Tests pour bot/push_notifications.py (FCM HTTP v1, sans réseau réel).

Utilise google-auth + requests (pas le SDK firebase-admin) : ce dernier
entraîne google-cloud-firestore/storage, jamais utilisés ici, qui imposent
protobuf<6 — en conflit avec d'autres projets Python partageant le même
environnement sur cette machine (tensorflow>=6.31, streamlit<7). Voir la
note en tête de bot/push_notifications.py.
"""
from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

from bot import config, push_notifications as push


class TestKeyPathResolution:
    """Priorité de résolution (debt D-6, docs/ARCHITECTURE_BLUEPRINT.md §11.3) :
    FIREBASE_ADMIN_KEY_PATH (env) > secrets/ (nouveau) > state/ (legacy, repli)."""

    def setup_method(self):
        self._save_secrets_dir = config.SECRETS_DIR
        self._save_state_dir = config.STATE_DIR
        push._warned_legacy_path = False

    def teardown_method(self):
        config.SECRETS_DIR = self._save_secrets_dir
        config.STATE_DIR = self._save_state_dir
        push._warned_legacy_path = False

    def test_env_override_wins_even_if_files_exist_elsewhere(self, tmp_path):
        config.SECRETS_DIR = str(tmp_path / "secrets")
        os.makedirs(config.SECRETS_DIR)
        (tmp_path / "secrets" / "firebase-adminsdk.json").write_text("{}")
        with patch.dict(os.environ, {"FIREBASE_ADMIN_KEY_PATH": "/explicit/path.json"}):
            assert push._key_path() == "/explicit/path.json"

    def test_prefers_new_secrets_location_when_present(self, tmp_path):
        config.SECRETS_DIR = str(tmp_path / "secrets")
        config.STATE_DIR = str(tmp_path / "state")
        os.makedirs(config.SECRETS_DIR)
        os.makedirs(config.STATE_DIR)
        (tmp_path / "secrets" / "firebase-adminsdk.json").write_text("{}")
        (tmp_path / "state" / "firebase-adminsdk.json").write_text("{}")
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("FIREBASE_ADMIN_KEY_PATH", None)
            assert push._key_path() == os.path.join(config.SECRETS_DIR, "firebase-adminsdk.json")

    def test_falls_back_to_legacy_state_location_with_warning(self, tmp_path):
        config.SECRETS_DIR = str(tmp_path / "secrets")
        config.STATE_DIR = str(tmp_path / "state")
        os.makedirs(config.STATE_DIR)
        (tmp_path / "state" / "firebase-adminsdk.json").write_text("{}")
        with patch.dict(os.environ, {}, clear=False), patch.object(push, "log") as log_mock:
            os.environ.pop("FIREBASE_ADMIN_KEY_PATH", None)
            path = push._key_path()
        assert path == os.path.join(config.STATE_DIR, "firebase-adminsdk.json")
        assert log_mock.called

    def test_legacy_warning_logs_only_once(self, tmp_path):
        config.SECRETS_DIR = str(tmp_path / "secrets")
        config.STATE_DIR = str(tmp_path / "state")
        os.makedirs(config.STATE_DIR)
        (tmp_path / "state" / "firebase-adminsdk.json").write_text("{}")
        with patch.dict(os.environ, {}, clear=False), patch.object(push, "log") as log_mock:
            os.environ.pop("FIREBASE_ADMIN_KEY_PATH", None)
            push._key_path()
            push._key_path()
        assert log_mock.call_count == 1

    def test_defaults_to_new_location_when_neither_exists(self, tmp_path):
        config.SECRETS_DIR = str(tmp_path / "secrets")
        config.STATE_DIR = str(tmp_path / "state")
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("FIREBASE_ADMIN_KEY_PATH", None)
            assert push._key_path() == os.path.join(config.SECRETS_DIR, "firebase-adminsdk.json")


class TestIsEnabled:
    def test_false_without_key_file(self):
        with patch.object(push, "_key_path", return_value="/nonexistent/path.json"):
            assert push.is_enabled() is False

    def test_true_with_key_file(self, tmp_path):
        key_file = tmp_path / "key.json"
        key_file.write_text("{}")
        with patch.object(push, "_key_path", return_value=str(key_file)):
            assert push.is_enabled() is True


class TestSendPush:
    def setup_method(self):
        push._cached_token = None
        push._cached_token_expiry = 0.0
        push._project_id = None

    def test_returns_none_when_disabled(self):
        with patch.object(push, "is_enabled", return_value=False):
            assert push.send_push("tok", "titre", "corps") is None

    def test_returns_true_on_200(self):
        with patch.object(push, "is_enabled", return_value=True), \
             patch.object(push, "_access_token", return_value="tok123"):
            push._project_id = "tennisboss-de863"
            resp = MagicMock(status_code=200)
            with patch.object(push.requests, "post", return_value=resp):
                assert push.send_push("device-token", "titre", "corps") is True

    def test_returns_false_on_invalid_token(self):
        with patch.object(push, "is_enabled", return_value=True), \
             patch.object(push, "_access_token", return_value="tok123"):
            push._project_id = "tennisboss-de863"
            resp = MagicMock(status_code=404, text="UNREGISTERED")
            with patch.object(push.requests, "post", return_value=resp):
                assert push.send_push("device-token", "titre", "corps") is False

    def test_returns_none_on_transient_server_error(self):
        with patch.object(push, "is_enabled", return_value=True), \
             patch.object(push, "_access_token", return_value="tok123"):
            push._project_id = "tennisboss-de863"
            resp = MagicMock(status_code=500, text="internal error")
            with patch.object(push.requests, "post", return_value=resp):
                assert push.send_push("device-token", "titre", "corps") is None

    def test_returns_none_on_network_error(self):
        with patch.object(push, "is_enabled", return_value=True), \
             patch.object(push, "_access_token", return_value="tok123"):
            push._project_id = "tennisboss-de863"
            with patch.object(push.requests, "post", side_effect=OSError("timeout")):
                assert push.send_push("device-token", "titre", "corps") is None


class TestBroadcast:
    def test_zero_when_disabled(self):
        with patch.object(push, "is_enabled", return_value=False):
            assert push.broadcast("titre", "corps") == 0

    def test_deletes_invalid_tokens_but_keeps_transient_failures(self):
        rows = [{"token": "valid"}, {"token": "invalid"}, {"token": "transient-fail"}]

        def fake_send(token, title, body, data=None):
            return {"valid": True, "invalid": False, "transient-fail": None}[token]

        with patch.object(push, "is_enabled", return_value=True), \
             patch("bot.db.list_device_tokens", return_value=rows), \
             patch.object(push, "send_push", side_effect=fake_send), \
             patch("bot.db.delete_device_token") as mock_delete:
            sent = push.broadcast("titre", "corps")

        assert sent == 1
        mock_delete.assert_called_once_with("invalid")
