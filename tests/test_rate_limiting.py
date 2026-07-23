"""Tests pour le rate-limiting de l'API (bot/api.py, flask_limiter).

Le trafic réel passe App -> Worker Cloudflare -> tunnel -> Flask local (voir
DEPLOYMENT.md) : un rate-limit par request.remote_addr verrait la même IP
(celle du tunnel) pour tous les clients — _client_ip() doit donc préférer
CF-Connecting-IP (ajouté par Cloudflare à l'edge, jamais falsifiable par le
client). C'est le point le plus important à couvrir ici.
"""
from __future__ import annotations

from unittest.mock import patch

from bot import api


def _fake_mem():
    return {"players": {}, "elo": {}, "elo_surface": {}, "weights": {},
            "bias": 0.0, "metrics": {}, "datasets_loaded": []}


def test_client_ip_prefers_cf_connecting_ip_header():
    with api.app.test_request_context(headers={"CF-Connecting-IP": "1.2.3.4"}):
        assert api._client_ip() == "1.2.3.4"


def test_client_ip_falls_back_to_remote_addr_without_cf_header():
    with api.app.test_request_context(environ_overrides={"REMOTE_ADDR": "9.9.9.9"}):
        assert api._client_ip() == "9.9.9.9"


def test_rate_limit_error_response_is_json():
    with api.app.test_request_context():
        class _FakeLimitExceeded:
            description = "20 per 1 minute"
        resp, status = api._rate_limit_exceeded(_FakeLimitExceeded())
    assert status == 429
    data = resp.get_json()
    assert "error" in data


class TestRateLimitEnforced:
    """Désactive temporairement l'exemption TESTING pour vérifier que la
    limite (20/min sur /api/value) se déclenche réellement au-delà du seuil."""

    def setup_method(self):
        api._MEM = _fake_mem()
        api.app.testing = True  # garde le mode test Flask (propagation des erreurs)
        api.app.config["TESTING"] = False  # mais désactive l'exemption du rate-limit
        self.client = api.app.test_client()
        api.limiter.reset()

    def teardown_method(self):
        api.app.config["TESTING"] = True
        api.limiter.reset()

    def test_21st_request_in_a_minute_is_rejected(self):
        with patch.object(api.odds_api, "is_enabled", return_value=False):
            responses = [self.client.get("/api/value") for _ in range(21)]
        codes = [r.status_code for r in responses]
        assert codes[:20] == [503] * 20  # ODDS_API_KEY absente, mais pas throttlé
        assert codes[20] == 429

    def test_different_client_ips_have_independent_budgets(self):
        with patch.object(api.odds_api, "is_enabled", return_value=False):
            for _ in range(20):
                self.client.get("/api/value", headers={"CF-Connecting-IP": "1.1.1.1"})
            resp_same_ip = self.client.get("/api/value", headers={"CF-Connecting-IP": "1.1.1.1"})
            resp_other_ip = self.client.get("/api/value", headers={"CF-Connecting-IP": "2.2.2.2"})
        assert resp_same_ip.status_code == 429
        assert resp_other_ip.status_code == 503  # budget indépendant, pas throttlé


class TestChatRateLimitEnforced:
    """/api/chat protège le coût LLM (debt D-17) — 20/min, même mécanisme
    d'exemption TESTING que TestRateLimitEnforced ci-dessus."""

    def setup_method(self):
        api._MEM = _fake_mem()
        api.app.testing = True
        api.app.config["TESTING"] = False
        self.client = api.app.test_client()
        api.limiter.reset()

    def teardown_method(self):
        api.app.config["TESTING"] = True
        api.limiter.reset()

    def test_21st_chat_request_in_a_minute_is_rejected(self):
        with patch.object(api.chat_mod, "build_match_context", return_value=""), \
             patch.object(api.chat_mod, "chat", return_value="reponse"):
            responses = [
                self.client.post("/api/chat", json={"message": "Bonjour"})
                for _ in range(21)
            ]
        codes = [r.status_code for r in responses]
        assert codes[:20] == [200] * 20
        assert codes[20] == 429


class TestAuthFailureThrottle:
    """Anti-brute-force sur les 401 (debt D-17) — budget dédié, indépendant du
    rate-limit général de trafic (200/min). Voir api._auth_failure_throttled /
    api._record_auth_failure."""

    def setup_method(self):
        api._auth_fail_log.clear()

    def teardown_method(self):
        api._auth_fail_log.clear()

    def test_not_throttled_before_max_failures(self):
        for _ in range(api._AUTH_FAIL_MAX - 1):
            api._record_auth_failure("3.3.3.3")
        assert api._auth_failure_throttled("3.3.3.3") is False

    def test_throttled_at_max_failures(self):
        for _ in range(api._AUTH_FAIL_MAX):
            api._record_auth_failure("4.4.4.4")
        assert api._auth_failure_throttled("4.4.4.4") is True

    def test_window_expiry_clears_throttle(self):
        with patch("bot.api.time.time", return_value=1_000_000.0):
            for _ in range(api._AUTH_FAIL_MAX):
                api._record_auth_failure("5.5.5.5")
        with patch("bot.api.time.time", return_value=1_000_000.0 + api._AUTH_FAIL_WINDOW_S + 1):
            assert api._auth_failure_throttled("5.5.5.5") is False

    def test_ips_have_independent_failure_budgets(self):
        for _ in range(api._AUTH_FAIL_MAX):
            api._record_auth_failure("6.6.6.6")
        assert api._auth_failure_throttled("6.6.6.6") is True
        assert api._auth_failure_throttled("7.7.7.7") is False

    def test_end_to_end_401_then_429_via_auth_hook(self):
        api._MEM = _fake_mem()
        api.app.testing = True
        api.app.config["TESTING"] = False  # active le throttle dans _auth()
        client = api.app.test_client()
        try:
            with patch.dict("os.environ", {"TENNISBOSS_API_TOKEN": "secret"}):
                responses = [
                    client.get("/health")  # public, jamais throttlé — sert de témoin
                ]
                bad = [
                    client.get("/api/status", headers={"CF-Connecting-IP": "8.8.8.8",
                                                        "X-API-Token": "wrong"})
                    for _ in range(api._AUTH_FAIL_MAX + 1)
                ]
            assert responses[0].status_code == 200
            codes = [r.status_code for r in bad]
            assert codes[:api._AUTH_FAIL_MAX] == [401] * api._AUTH_FAIL_MAX
            assert codes[-1] == 429
        finally:
            api.app.config["TESTING"] = True
            api._auth_fail_log.clear()
