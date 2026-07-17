"""Tests pour les plans d'authentification de bot/api.py (roadmap Q3 #3).

Deux ajouts additifs (docs/ARCHITECTURE_BLUEPRINT.md §8.1/§11) :
- Plan admin : si TENNISBOSS_ADMIN_TOKEN est défini, les routes d'écriture
  (settlement, learn, ingest, backfill, inplay picks POST/PUT/DELETE) exigent
  X-Admin-Token en plus du token client. Sans admin token : comportement
  historique inchangé.
- Default-deny prod : TENNISBOSS_ENV=prod sans TENNISBOSS_API_TOKEN refuse de
  démarrer (SystemExit) au lieu de servir en warn-only.
"""
from __future__ import annotations

from unittest import mock

import pytest

from bot import api

CLIENT = {"TENNISBOSS_API_TOKEN": "client-tok", "TENNISBOSS_ADMIN_TOKEN": ""}
BOTH = {"TENNISBOSS_API_TOKEN": "client-tok", "TENNISBOSS_ADMIN_TOKEN": "admin-tok"}
NONE = {"TENNISBOSS_API_TOKEN": "", "TENNISBOSS_ADMIN_TOKEN": ""}


def _auth_result(path: str, method: str = "GET", headers: dict | None = None):
    with api.app.test_request_context(path, method=method, headers=headers or {}):
        return api._auth()


class TestAdminPlane:
    def test_admin_route_unchanged_when_admin_token_unset(self):
        with mock.patch.dict("os.environ", CLIENT):
            out = _auth_result("/api/settlement/run",
                               headers={"X-API-Token": "client-tok"})
        assert out is None  # token client suffit, comme avant

    def test_client_token_alone_is_rejected_on_admin_route(self):
        with mock.patch.dict("os.environ", BOTH):
            out = _auth_result("/api/settlement/run",
                               headers={"X-API-Token": "client-tok"})
        assert out is not None
        _, status = out
        assert status == 403

    def test_both_tokens_allow_admin_route(self):
        with mock.patch.dict("os.environ", BOTH):
            out = _auth_result(
                "/api/learn/run", method="POST",
                headers={"X-API-Token": "client-tok", "X-Admin-Token": "admin-tok"})
        assert out is None

    def test_wrong_admin_token_is_rejected(self):
        with mock.patch.dict("os.environ", BOTH):
            out = _auth_result(
                "/api/ingest/sackmann", method="POST",
                headers={"X-API-Token": "client-tok", "X-Admin-Token": "wrong"})
        assert out is not None and out[1] == 403

    def test_client_routes_unaffected_by_admin_token(self):
        with mock.patch.dict("os.environ", BOTH):
            out = _auth_result("/api/status",
                               headers={"X-API-Token": "client-tok"})
        assert out is None

    def test_inplay_picks_stay_client_plane_even_for_writes(self):
        # Les picks manuels sont saisis depuis l'app Android avec le seul token
        # client (POST/PUT/DELETE api/inplay/picks, TennisBossApi.kt) : ce sont
        # des données UTILISATEUR, pas de l'administration serveur. Ce test
        # garantit qu'activer TENNISBOSS_ADMIN_TOKEN ne casse pas l'app.
        with mock.patch.dict("os.environ", BOTH):
            read = _auth_result("/api/inplay/picks",
                                headers={"X-API-Token": "client-tok"})
            write = _auth_result("/api/inplay/picks", method="POST",
                                 headers={"X-API-Token": "client-tok"})
            delete = _auth_result("/api/inplay/picks/7", method="DELETE",
                                  headers={"X-API-Token": "client-tok"})
        assert read is None
        assert write is None
        assert delete is None

    def test_client_401_still_takes_precedence(self):
        with mock.patch.dict("os.environ", BOTH):
            out = _auth_result("/api/settlement/run",
                               headers={"X-Admin-Token": "admin-tok"})
        assert out is not None and out[1] == 401  # pas de token client


class TestProdDefaultDeny:
    def test_prod_without_token_refuses_to_start(self):
        env = dict(NONE, TENNISBOSS_ENV="prod")
        with mock.patch.dict("os.environ", env), pytest.raises(SystemExit):
            api._enforce_prod_token("0.0.0.0")

    def test_prod_with_token_starts_and_returns_it(self):
        env = dict(CLIENT, TENNISBOSS_ENV="prod")
        with mock.patch.dict("os.environ", env):
            assert api._enforce_prod_token("0.0.0.0") == "client-tok"

    def test_dev_without_token_only_warns(self):
        env = dict(NONE, TENNISBOSS_ENV="dev")
        with mock.patch.dict("os.environ", env), \
                mock.patch("bot.log.log") as log_mock:
            assert api._enforce_prod_token("0.0.0.0") == ""
        assert any("SÉCURITÉ" in str(c.args[0]) for c in log_mock.call_args_list)

    def test_dev_localhost_without_token_is_silent(self):
        env = dict(NONE, TENNISBOSS_ENV="dev")
        with mock.patch.dict("os.environ", env), \
                mock.patch("bot.log.log") as log_mock:
            assert api._enforce_prod_token("127.0.0.1") == ""
        assert log_mock.call_args_list == []
