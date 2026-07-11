"""Tests HTTP pour /api/insight (Sport Intelligence Layer, Phase 1).

Premier test au niveau app.test_client() du projet (jusqu'ici, les 147 tests
existants ne testaient que les modules sous-jacents, jamais le routing Flask
lui-même — voir audit Étape 3). On ne fait pas tourner _load_state() (accès
réseau/DB réels) : on peuple directement bot.api._MEM avec un fixture, comme
le fait déjà tests/test_chat.py pour bot/chat.py.
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


# Bilans carrière alignés sur la forme récente du fixture (recent=1.0/0.95)
# -> aucune bascule de forme signalée dans les tests qui ne testent pas ça.
_STABLE_RECORDS = {
    "Jannik Sinner": {"wins": 100, "losses": 0},
    "Carlos Alcaraz": {"wins": 95, "losses": 5},
}


def test_insight_requires_both_players():
    resp = _client().get("/api/insight?p1=Jannik+Sinner")
    assert resp.status_code == 400


def test_insight_returns_factors_and_health():
    with patch.object(api.db, "head_to_head", return_value=[]), \
         patch.object(api.db, "player_record", side_effect=lambda n: _STABLE_RECORDS[n]), \
         patch.object(api.intelligence, "stats", return_value={
             "blacklist": [], "surface_danger": [], "accuracy_drift_pts": 0.0,
         }), \
         patch.object(api.db, "line_movement", return_value=None):
        resp = _client().get("/api/insight?p1=Jannik+Sinner&p2=Carlos+Alcaraz")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["player1"] == "Jannik Sinner"
    assert data["player2"] == "Carlos Alcaraz"
    assert data["confidence_label"]
    assert data["decisive_factor"]
    assert any(f["label"] == "Niveau ELO (historique)" for f in data["factors"])
    assert data["form_signals"] == []
    assert data["sentiment_signals"] == []
    assert data["market"] is None
    assert data["model_health"] == {
        "player1_blacklisted": False,
        "player2_blacklisted": False,
        "surface_danger": False,
        "accuracy_drift_pts": 0.0,
    }


def test_insight_flags_blacklisted_player():
    with patch.object(api.db, "head_to_head", return_value=[]), \
         patch.object(api.db, "player_record", side_effect=lambda n: _STABLE_RECORDS[n]), \
         patch.object(api.intelligence, "stats", return_value={
             "blacklist": ["Carlos Alcaraz"], "surface_danger": ["clay"], "accuracy_drift_pts": -6.0,
         }), \
         patch.object(api.db, "line_movement", return_value=None):
        resp = _client().get(
            "/api/insight?p1=Jannik+Sinner&p2=Carlos+Alcaraz&surface=clay&event_id=42"
        )
    data = resp.get_json()
    assert data["model_health"]["player2_blacklisted"] is True
    assert data["model_health"]["surface_danger"] is True
    assert data["model_health"]["accuracy_drift_pts"] == -6.0


def test_insight_includes_market_movement_when_available():
    fake_move = {"event_key": "42", "n_snapshots": 3, "move_home_pct": -12.5, "move_away_pct": 8.0}
    with patch.object(api.db, "head_to_head", return_value=[]), \
         patch.object(api.db, "player_record", side_effect=lambda n: _STABLE_RECORDS[n]), \
         patch.object(api.intelligence, "stats", return_value={
             "blacklist": [], "surface_danger": [], "accuracy_drift_pts": 0.0,
         }), \
         patch.object(api.db, "line_movement", return_value=fake_move) as mocked:
        resp = _client().get("/api/insight?p1=Jannik+Sinner&p2=Carlos+Alcaraz&event_id=42")
    mocked.assert_called_once_with("42")
    assert resp.get_json()["market"] == fake_move


def test_insight_flags_form_swing():
    # Alcaraz : forme récente 95% vs bilan carrière 50% -> bascule (surperformance).
    records = {
        "Jannik Sinner": {"wins": 100, "losses": 0},
        "Carlos Alcaraz": {"wins": 50, "losses": 50},
    }
    with patch.object(api.db, "head_to_head", return_value=[]), \
         patch.object(api.db, "player_record", side_effect=lambda n: records[n]), \
         patch.object(api.intelligence, "stats", return_value={
             "blacklist": [], "surface_danger": [], "accuracy_drift_pts": 0.0,
         }), \
         patch.object(api.db, "line_movement", return_value=None):
        resp = _client().get("/api/insight?p1=Jannik+Sinner&p2=Carlos+Alcaraz")
    signals = resp.get_json()["form_signals"]
    assert len(signals) == 1
    assert signals[0]["player"] == "Carlos Alcaraz"
    assert signals[0]["direction"] == "surperformance"


def test_insight_sentiment_is_opt_in():
    # Sans ?sentiment=true, aucun appel réseau/quota consommé (voir note
    # Phase 3 dans intelligence_layer.py : quota NewsAPI très serré).
    with patch.object(api.db, "head_to_head", return_value=[]), \
         patch.object(api.db, "player_record", side_effect=lambda n: _STABLE_RECORDS[n]), \
         patch.object(api.intelligence, "stats", return_value={
             "blacklist": [], "surface_danger": [], "accuracy_drift_pts": 0.0,
         }), \
         patch.object(api.db, "line_movement", return_value=None), \
         patch.object(api.intelligence_layer.sentiment, "is_enabled", return_value=True), \
         patch.object(api.intelligence_layer.sentiment, "player_sentiment") as mocked:
        resp = _client().get("/api/insight?p1=Jannik+Sinner&p2=Carlos+Alcaraz")
    mocked.assert_not_called()
    assert resp.get_json()["sentiment_signals"] == []


def test_insight_sentiment_included_when_requested():
    fake_sentiment = {"player": "Jannik Sinner", "n_articles": 3, "score": 0.5,
                      "label": "positif", "headlines": ["Sinner wins"]}
    with patch.object(api.db, "head_to_head", return_value=[]), \
         patch.object(api.db, "player_record", side_effect=lambda n: _STABLE_RECORDS[n]), \
         patch.object(api.intelligence, "stats", return_value={
             "blacklist": [], "surface_danger": [], "accuracy_drift_pts": 0.0,
         }), \
         patch.object(api.db, "line_movement", return_value=None), \
         patch.object(api.intelligence_layer.sentiment, "is_enabled", return_value=True), \
         patch.object(api.intelligence_layer.sentiment, "player_sentiment",
                      side_effect=lambda n: fake_sentiment if n == "Jannik Sinner" else None):
        resp = _client().get("/api/insight?p1=Jannik+Sinner&p2=Carlos+Alcaraz&sentiment=true")
    signals = resp.get_json()["sentiment_signals"]
    assert len(signals) == 1
    assert signals[0]["player"] == "Jannik Sinner"
