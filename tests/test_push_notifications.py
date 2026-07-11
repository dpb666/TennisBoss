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

from bot import push_notifications as push


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
