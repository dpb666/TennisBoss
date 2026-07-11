"""Tests HTTP (app.test_client()) pour /api/value, /api/live, /api/calibration.

Étape 4 du plan de stabilisation : ces 3 endpoints avaient été identifiés à
l'audit Étape 3 comme prioritaires (les plus consommés par l'app Android,
logique de fallback/rate-limit non triviale) parmi les 33 endpoints de
bot/api.py sans aucun test au niveau routing Flask. Suit le même pattern que
tests/test_api_insight.py (fixture _MEM, pas de _load_state()).
"""
from __future__ import annotations

from unittest.mock import patch

from bot import api


def _fake_mem():
    return {
        "players": {
            "Jannik Sinner": {"serve": 0.72, "return1": 0.55, "return2": 0.58, "recent": 1.0, "n": 321},
            "Carlos Alcaraz": {"serve": 0.70, "return1": 0.53, "return2": 0.56, "recent": 0.95, "n": 280},
        },
        "elo": {"Jannik Sinner": 2112.0, "Carlos Alcaraz": 2085.0},
        "weights": {"serve": 1.2, "return1": 0.8, "return2": 0.6, "recent": 0.5},
        "bias": 0.0,
        "metrics": {"accuracy": 0.644},
    }


def _client():
    api._MEM = _fake_mem()
    api.app.testing = True
    return api.app.test_client()


# ─── /api/value ──────────────────────────────────────────────────────────────

def test_value_returns_503_without_odds_key():
    with patch.object(api.odds_api, "is_enabled", return_value=False):
        resp = _client().get("/api/value")
    assert resp.status_code == 503
    assert "error" in resp.get_json()


def test_value_reports_rate_limited_when_key_pool_exhausted():
    with patch.object(api.odds_api, "is_enabled", return_value=True), \
         patch.object(api.odds_api, "_current_key", return_value=None), \
         patch.object(api.odds_api, "rate_limit_status", return_value={
             "pool": [{"reset_in_s": 42}],
         }):
        resp = _client().get("/api/value")
    data = resp.get_json()
    assert resp.status_code == 200
    assert data["rate_limited"] is True
    assert data["retry_in_s"] == 42
    assert data["comparisons"] == []


def test_value_falls_back_to_db_picks_when_no_live_events():
    with patch.object(api.odds_api, "is_enabled", return_value=True), \
         patch.object(api.odds_api, "_current_key", return_value="k"), \
         patch.object(api.odds_api, "fetch_tennis_events", return_value=[]), \
         patch.object(api.db, "list_value_picks", return_value=[]):
        resp = _client().get("/api/value")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["count"] == 0
    assert data["comparisons"] == []


# ─── /api/live ───────────────────────────────────────────────────────────────

def test_live_returns_503_without_odds_key():
    with patch.object(api.odds_api, "is_enabled", return_value=False):
        resp = _client().get("/api/live")
    assert resp.status_code == 503
    assert "error" in resp.get_json()


def test_live_returns_empty_matches_when_nothing_live():
    with patch.object(api.odds_api, "is_enabled", return_value=True), \
         patch.object(api.odds_api, "fetch_live_events", return_value=[]), \
         patch.object(api.db, "auto_settle_picks", return_value=[]):
        resp = _client().get("/api/live")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data == {"count": 0, "matches": []}


# ─── /api/calibration ────────────────────────────────────────────────────────

def test_calibration_returns_metrics_and_learned_factors():
    with patch.object(api.settlement, "calibration_metrics", return_value={"accuracy": 0.61, "n": 120}), \
         patch.object(api.db, "list_settled", return_value=[]):
        resp = _client().get("/api/calibration")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["metrics"] == {"accuracy": 0.61, "n": 120}
    assert "calibration_k" in data
    assert "platt_a" in data and "platt_b" in data
    assert data["recent"] == []
