"""Tests pour bot/monitor.py.

Aucun test n'existait avant pour ce module — c'est ce qui a laissé passer
deux bugs réels en production (voir Git log) :
1. check_api_endpoints() n'envoyait jamais X-API-Token : dès que
   TENNISBOSS_API_TOKEN a été activé (session antérieure), chaque cycle de
   5 minutes générait une fausse alerte 401 sur /api/status, /api/value,
   /api/upcoming — le monitor était aveugle à ses propres échecs.
2. check_model_drift() comparait la précision ALL-TIME à une constante
   codée en dur (0.62) au lieu d'utiliser la fenêtre glissante déjà
   correctement implémentée dans bot/intelligence.py — ne pouvait jamais
   détecter une vraie dérive récente (diluée dans tout l'historique).
3. check_api_endpoints() ciblait "http://localhost:8000" en dur : correct
   quand tout tourne sur le même hôte (systemd), mais faux dès que le
   worker (bot/scheduler.py) tourne dans un conteneur Docker SÉPARÉ de
   l'API (docker-compose.yml) — "localhost" dans le worker ne pointe pas
   vers le conteneur API.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from bot.monitor import SystemMonitor


def _monitor() -> SystemMonitor:
    with patch("bot.monitor.memory.load", return_value={"players": {}}):
        return SystemMonitor()


class TestCheckApiEndpoints:
    def test_sends_api_token_header_when_configured(self):
        mon = _monitor()
        captured_requests = []

        def fake_urlopen(req, timeout=5):
            captured_requests.append(req)
            resp = MagicMock()
            resp.status = 200
            return resp

        with patch.dict("os.environ", {"TENNISBOSS_API_TOKEN": "secret123"}), \
             patch("urllib.request.urlopen", side_effect=fake_urlopen):
            result = mon.check_api_endpoints()

        assert all(r["status"] == "ok" for r in result.values())
        assert mon.alerts == []
        # /health n'a pas besoin du token côté serveur, mais rien n'empêche
        # de l'envoyer partout — on vérifie juste qu'il est bien présent.
        assert all(req.get_header("X-api-token") == "secret123" for req in captured_requests)

    def test_no_token_header_when_not_configured(self):
        mon = _monitor()
        captured_requests = []

        def fake_urlopen(req, timeout=5):
            captured_requests.append(req)
            resp = MagicMock()
            resp.status = 200
            return resp

        env_without_token = {"TENNISBOSS_API_TOKEN": ""}
        with patch.dict("os.environ", env_without_token), \
             patch("urllib.request.urlopen", side_effect=fake_urlopen):
            mon.check_api_endpoints()

        assert all(req.get_header("X-api-token") is None for req in captured_requests)

    def test_alerts_on_real_failure(self):
        mon = _monitor()
        with patch.dict("os.environ", {"TENNISBOSS_API_TOKEN": ""}), \
             patch("urllib.request.urlopen", side_effect=OSError("connection refused")):
            result = mon.check_api_endpoints()
        assert all(r["status"] == "error" for r in result.values())
        assert len(mon.alerts) == 4

    def test_uses_configurable_base_url_for_docker_worker(self):
        """TENNISBOSS_API_BASE_URL doit être respectée : c'est ce qui permet
        au worker (conteneur séparé) de joindre l'API par son nom de service
        Compose ("http://tennisboss:8000") plutôt que "localhost"."""
        mon = _monitor()
        captured_urls = []

        def fake_urlopen(req, timeout=5):
            captured_urls.append(req.full_url)
            resp = MagicMock()
            resp.status = 200
            return resp

        with patch.dict("os.environ", {"TENNISBOSS_API_BASE_URL": "http://tennisboss:8000"}), \
             patch("urllib.request.urlopen", side_effect=fake_urlopen):
            mon.check_api_endpoints()

        assert all(url.startswith("http://tennisboss:8000") for url in captured_urls)

    def test_defaults_to_localhost_without_base_url_configured(self):
        mon = _monitor()
        captured_urls = []

        def fake_urlopen(req, timeout=5):
            captured_urls.append(req.full_url)
            resp = MagicMock()
            resp.status = 200
            return resp

        env_without_base_url = {"TENNISBOSS_API_BASE_URL": ""}
        with patch.dict("os.environ", env_without_base_url), \
             patch("urllib.request.urlopen", side_effect=fake_urlopen):
            mon.check_api_endpoints()

        assert all(url.startswith("http://localhost:8000") for url in captured_urls)


class TestCheckModelDrift:
    def test_low_data_when_few_settled_matches(self):
        mon = _monitor()
        with patch("bot.monitor.settlement.calibration_metrics", return_value={"n": 10}):
            result = mon.check_model_drift()
        assert result["status"] == "low_data"

    def test_uses_rolling_window_drift_not_static_baseline(self):
        """Le check ne doit PAS déclencher sur une précision all-time basse si
        bot.intelligence (fenêtre glissante) ne signale aucune dérive récente —
        contrairement à l'ancien code qui comparait à la constante 0.62."""
        mon = _monitor()
        with patch("bot.monitor.settlement.calibration_metrics",
                   return_value={"n": 100, "accuracy": 0.55, "roi": 0.0}), \
             patch("bot.monitor.intelligence.stats",
                   return_value={"accuracy_drift_pts": 0.0, "thresholds": {"drift_alert_pts": 5.0}}):
            mon.check_model_drift()
        assert mon.alerts == []

    def test_alerts_when_rolling_window_shows_real_drift(self):
        mon = _monitor()
        with patch("bot.monitor.settlement.calibration_metrics",
                   return_value={"n": 100, "accuracy": 0.60, "roi": 0.0}), \
             patch("bot.monitor.intelligence.stats",
                   return_value={"accuracy_drift_pts": -8.0, "thresholds": {"drift_alert_pts": 5.0}}):
            mon.check_model_drift()
        assert len(mon.alerts) == 1
        assert "drift" in mon.alerts[0].lower()
