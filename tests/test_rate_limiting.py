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
