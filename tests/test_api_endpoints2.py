"""Tests HTTP (app.test_client()) pour les endpoints restants de bot/api.py.

Suite de tests/test_api_endpoints.py (value/live/calibration) : étend la
couverture Étape 4 à health/status/players/h2h/player/predict, inplay/best,
inplay/markets, clv, line-movement, intelligence/*, learner/stats,
scanner/status, learn/run, ingest/*, chat, upload. Un cas nominal (+ un cas
d'erreur clé quand pertinent) par endpoint, pas une couverture exhaustive.

value/open, value/history, history et les CRUD inplay/picks touchent la DB
directement (SELECT/INSERT bruts) plutôt que des fonctions mockables
proprement : voir tests/test_api_endpoints_db.py (DB temporaire, comme
tests/test_settlement.py).
"""
from __future__ import annotations

from unittest.mock import patch

from bot import api


def _fake_mem():
    return {
        "players": {
            "Jannik Sinner": {"serve": 0.72, "return1": 0.55, "return2": 0.58, "recent": 1.0, "n": 321, "tour": "atp"},
            "Carlos Alcaraz": {"serve": 0.70, "return1": 0.53, "return2": 0.56, "recent": 0.95, "n": 280, "tour": "atp"},
        },
        "elo": {"Jannik Sinner": 2112.0, "Carlos Alcaraz": 2085.0},
        "elo_surface": {},
        "elo_blend": 0.4,
        "weights": {"serve": 1.2, "return1": 0.8, "return2": 0.6, "recent": 0.5},
        "bias": 0.0,
        "metrics": {"accuracy": 0.644},
        "datasets_loaded": ["sackmann"],
    }


def _client():
    api._MEM = _fake_mem()
    api.app.testing = True
    return api.app.test_client()


# ─── health / status ─────────────────────────────────────────────────────────

def test_health_ok():
    resp = _client().get("/health")
    data = resp.get_json()
    assert resp.status_code == 200
    assert data["status"] == "ok"
    assert data["players_loaded"] == 2


def test_privacy_policy_serves_html():
    resp = _client().get("/privacy")
    assert resp.status_code == 200
    assert resp.content_type.startswith("text/html")
    assert b"<h1>" in resp.data


def test_status_returns_metrics_and_db_counts():
    with patch.object(api.db, "counts", return_value={"players": 2, "matches": 10}), \
         patch.object(api.odds_api, "rate_limit_status", return_value={"pool": []}):
        resp = _client().get("/api/status")
    data = resp.get_json()
    assert resp.status_code == 200
    assert data["db"] == {"players": 2, "matches": 10}
    assert data["metrics"] == {"accuracy": 0.644}


# ─── players / h2h / player ──────────────────────────────────────────────────

def test_players_search_filters_by_query():
    with patch.object(api.db, "list_followed_players", return_value=[]):
        resp = _client().get("/api/players?q=sinner")
    data = resp.get_json()
    assert resp.status_code == 200
    assert data["count"] == 2  # total joueurs connus
    assert len(data["players"]) == 1
    assert data["players"][0]["name"] == "Jannik Sinner"
    assert data["players"][0]["followed"] is False


def test_players_search_flags_followed_player():
    with patch.object(api.db, "list_followed_players", return_value=["Jannik Sinner"]):
        resp = _client().get("/api/players?q=sinner")
    assert resp.get_json()["players"][0]["followed"] is True


def test_h2h_requires_both_players():
    resp = _client().get("/api/h2h?p1=Jannik+Sinner")
    assert resp.status_code == 400


def test_h2h_returns_404_for_unknown_player():
    resp = _client().get("/api/h2h?p1=Jannik+Sinner&p2=Nobody+Unknown")
    assert resp.status_code == 404


def test_h2h_returns_meetings_for_known_players():
    with patch.object(api.db, "head_to_head", return_value=[]):
        resp = _client().get("/api/h2h?p1=Jannik+Sinner&p2=Carlos+Alcaraz")
    data = resp.get_json()
    assert resp.status_code == 200
    assert data["player1"] == "Jannik Sinner"
    assert data["total"] == 0


def test_player_requires_name():
    resp = _client().get("/api/player")
    assert resp.status_code == 400


def test_player_returns_404_for_unknown():
    resp = _client().get("/api/player?name=Nobody+Unknown")
    assert resp.status_code == 404


def test_player_returns_profile_for_known_player():
    with patch.object(api.db, "player_record", return_value={"wins": 10, "losses": 5}), \
         patch.object(api.db, "player_recent_matches", return_value=[]), \
         patch.object(api.db, "get_player", return_value=None), \
         patch.object(api.db, "is_player_followed", return_value=False):
        resp = _client().get("/api/player?name=Jannik+Sinner")
    data = resp.get_json()
    assert resp.status_code == 200
    assert data["name"] == "Jannik Sinner"
    assert data["record"]["wins"] == 10
    assert data["elo"]["rating"] == 2112.0
    assert data["followed"] is False


# ─── predict ──────────────────────────────────────────────────────────────────

def test_predict_requires_both_players():
    resp = _client().get("/api/predict?p1=Jannik+Sinner")
    assert resp.status_code == 400


def test_predict_returns_first_set_probabilities():
    with patch.object(api.db, "log_prediction"), \
         patch.object(api.db, "head_to_head", return_value=[]):
        resp = _client().get("/api/predict?p1=Jannik+Sinner&p2=Carlos+Alcaraz")
    data = resp.get_json()
    assert resp.status_code == 200
    assert data["player1"]["name"] == "Jannik Sinner"
    assert "first_set" in data
    assert "explain" in data


# ─── upcoming ─────────────────────────────────────────────────────────────────

def test_upcoming_returns_empty_when_no_source_has_fixtures():
    with patch.object(api.live_api, "fetch_upcoming", return_value=[]), \
         patch.object(api.espn_api, "fetch_upcoming", return_value=[]), \
         patch.object(api.odds_api, "is_enabled", return_value=False):
        # limit=99 (unique) évite de retomber sur le cache d'un autre test.
        resp = _client().get("/api/upcoming?days=1&limit=99")
    data = resp.get_json()
    assert resp.status_code == 200
    assert data["matches"] == []


# ─── settlement/run ───────────────────────────────────────────────────────────

def test_settlement_run_returns_summary_and_calibration():
    fake_summary = {"settled": 2, "logged": 2}
    fake_metrics = {"accuracy": 0.6, "n": 50}
    with patch.object(api.settlement, "run_settlement", return_value=fake_summary), \
         patch.object(api, "_refit_calibration", return_value={"platt": {}, "temperature": {}}), \
         patch.object(api.settlement, "calibration_metrics", return_value=fake_metrics), \
         patch.object(api.db, "save_calibration"):
        resp = _client().get("/api/settlement/run?days=1")
    data = resp.get_json()
    assert resp.status_code == 200
    assert data["settlement"] == fake_summary
    assert data["calibration"] == fake_metrics


# ─── inplay/best & inplay/markets ────────────────────────────────────────────

def test_inplay_best_returns_503_without_odds_key():
    with patch.object(api.odds_api, "is_enabled", return_value=False):
        resp = _client().get("/api/inplay/best")
    assert resp.status_code == 503


def test_inplay_best_returns_empty_when_nothing_live():
    with patch.object(api.odds_api, "is_enabled", return_value=True), \
         patch.object(api.odds_api, "fetch_live_events", return_value=[]):
        resp = _client().get("/api/inplay/best")
    data = resp.get_json()
    assert resp.status_code == 200
    assert data == {"count": 0, "best": [],
                    "note": "Score = confiance × edge_vs_marché. Haut score = meilleur pick selon la DB."}


def test_inplay_markets_returns_503_without_odds_key():
    with patch.object(api.odds_api, "is_enabled", return_value=False):
        resp = _client().get("/api/inplay/markets")
    assert resp.status_code == 503


def test_inplay_markets_returns_empty_when_nothing_live():
    with patch.object(api.odds_api, "is_enabled", return_value=True), \
         patch.object(api.odds_api, "fetch_live_events", return_value=[]):
        resp = _client().get("/api/inplay/markets")
    data = resp.get_json()
    assert resp.status_code == 200
    assert data["count"] == 0
    assert data["matches"] == []


# ─── clv / line-movement ──────────────────────────────────────────────────────

def test_clv_returns_stats_and_recent():
    with patch.object(api.clv, "stats", return_value={"n_clv": 0, "verdict": "insuffisant"}), \
         patch.object(api.db, "list_clv", return_value=[]):
        resp = _client().get("/api/clv")
    data = resp.get_json()
    assert resp.status_code == 200
    assert data["verdict"] == "insuffisant"
    assert data["recent"] == []


def test_line_movement_without_event_id_returns_totals():
    with patch.object(api.db, "connect") as mock_connect:
        conn = mock_connect.return_value.__enter__.return_value
        conn.execute.return_value.fetchone.side_effect = [(42,), (7,)]
        resp = _client().get("/api/line-movement")
    data = resp.get_json()
    assert resp.status_code == 200
    assert data == {"total_snapshots": 42, "matchs_distincts": 7,
                    "note": "passer ?event_id=XXX pour le détail d'un match"}


def test_line_movement_with_unknown_event_id():
    with patch.object(api.db, "line_movement", return_value=None):
        resp = _client().get("/api/line-movement?event_id=999")
    data = resp.get_json()
    assert resp.status_code == 200
    assert "error" in data


# ─── intelligence / learner / scanner ────────────────────────────────────────

def test_intelligence_stats():
    with patch.object(api.intelligence, "stats", return_value={"blacklist": []}):
        resp = _client().get("/api/intelligence/stats")
    data = resp.get_json()
    assert resp.status_code == 200
    assert data["ok"] is True
    assert data["blacklist"] == []


def test_intelligence_cycle_forces_a_run():
    with patch.object(api.intelligence, "run_cycle", return_value={"drift": 0.0}) as mocked:
        resp = _client().post("/api/intelligence/cycle")
    mocked.assert_called_once_with(send_telegram=False)
    data = resp.get_json()
    assert resp.status_code == 200
    assert data["ok"] is True


def test_learner_stats():
    with patch.object(api.mistake_learner, "stats", return_value={"danger_zones": []}):
        resp = _client().get("/api/learner/stats")
    data = resp.get_json()
    assert resp.status_code == 200
    assert data["danger_zones"] == []


def test_scanner_status():
    resp = _client().get("/api/scanner/status")
    data = resp.get_json()
    assert resp.status_code == 200
    assert data["ok"] is True


def test_learn_run_rejects_when_too_recent():
    import time
    with patch.object(api, "_LEARN_LAST_RUN", time.time()):
        resp = _client().post("/api/learn/run")
    assert resp.status_code == 429
    assert resp.get_json()["status"] == "skipped"


# ─── ingest ───────────────────────────────────────────────────────────────────

def test_ingest_sackmann_returns_ok():
    fake_counts = {"new_players": 3, "inserted": 12}
    with patch.object(api.sackmann_feeder, "ingest_year_range", return_value=fake_counts), \
         patch.object(api.memory, "load", return_value=_fake_mem()), \
         patch.object(api.namematch, "build_index", return_value={}):
        resp = _client().post("/api/ingest/sackmann")
    data = resp.get_json()
    assert resp.status_code == 200
    assert data["status"] == "ok"
    assert data["ingest"] == fake_counts


def test_ingest_sackmann_returns_500_on_error():
    with patch.object(api.sackmann_feeder, "ingest_year_range", side_effect=RuntimeError("boom")):
        resp = _client().post("/api/ingest/sackmann")
    assert resp.status_code == 500
    assert "error" in resp.get_json()


def test_ingest_tennisdata_returns_ok():
    fake_counts = {"new_players": 1, "inserted": 4}
    with patch("bot.tennisdata_feeder.ingest", return_value=fake_counts), \
         patch.object(api.memory, "load", return_value=_fake_mem()), \
         patch.object(api.namematch, "build_index", return_value={}):
        resp = _client().post("/api/ingest/tennisdata")
    data = resp.get_json()
    assert resp.status_code == 200
    assert data["ingest"] == fake_counts


# ─── chat / upload ────────────────────────────────────────────────────────────

def test_chat_requires_message():
    resp = _client().post("/api/chat", json={})
    assert resp.status_code == 400


def test_chat_returns_reply():
    with patch.object(api.chat_mod, "build_match_context", return_value=""), \
         patch.object(api.chat_mod, "chat", return_value="Sinner est favori."):
        resp = _client().post("/api/chat", json={"message": "Qui va gagner ?"})
    data = resp.get_json()
    assert resp.status_code == 200
    assert data["reply"] == "Sinner est favori."


def test_chat_returns_503_when_llm_unreachable():
    with patch.object(api.chat_mod, "build_match_context", return_value=""), \
         patch.object(api.chat_mod, "chat", side_effect=RuntimeError("timeout")):
        resp = _client().post("/api/chat", json={"message": "Qui va gagner ?"})
    assert resp.status_code == 503


def test_upload_requires_file():
    resp = _client().post("/api/upload", data={})
    assert resp.status_code == 400


def test_device_register_requires_token():
    resp = _client().post("/api/device/register", json={})
    assert resp.status_code == 400


def test_device_register_success():
    with patch.object(api.db, "register_device_token") as mocked:
        resp = _client().post("/api/device/register", json={"token": "abc123"})
    assert resp.status_code == 200
    assert resp.get_json()["status"] == "registered"
    mocked.assert_called_once_with("abc123", "android")


def test_upload_returns_extracted_text():
    import io
    with patch("bot.file_parser.parse", return_value=("contenu extrait", "txt")):
        resp = _client().post(
            "/api/upload",
            data={"file": (io.BytesIO(b"hello"), "notes.txt")},
            content_type="multipart/form-data",
        )
    data = resp.get_json()
    assert resp.status_code == 200
    assert data["extracted_text"] == "contenu extrait"
